"""Migrations, seed data and integrity rules enforced inside PostgreSQL."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR
from mixt.models import Base
from mixt.modules.audit import service as audit
from mixt.modules.crm.models import Account, Consent, Contact
from mixt.modules.identity.catalogue import PERMISSIONS, ROLES
from mixt.modules.identity.models import Permission, Role, RolePermission
from mixt.modules.reference.models import Country, Curriculum, ExamBoard, Market, Qualification
from tests.conftest import TEST_DATABASE_URL, alembic_config, reset_database

# BD-004: confirmed operating markets (2026-11-09).
CONFIRMED_MARKETS = {"AE", "QA", "KW", "SA", "OM", "BH", "MY", "HK", "SG", "ID", "KR", "GB", "IE"}


@pytest.fixture(scope="module")
def scratch_url() -> str:
    """A separate database for up/down migration tests."""
    base = TEST_DATABASE_URL.rsplit("/", 1)[0]
    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS mixt_migration_check"))
        conn.execute(text("CREATE DATABASE mixt_migration_check"))
    admin.dispose()
    return base + "/mixt_migration_check"


def test_migrations_upgrade_downgrade_upgrade(scratch_url: str) -> None:
    cfg = alembic_config(scratch_url)
    reset_database(scratch_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(scratch_url)
    with engine.connect() as conn:
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
        functions = (
            conn.execute(
                text(
                    "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public' AND proname IN ('audit_log_chain','reject_modification',"
                    "'markets_reject_excluded_country','countries_guard_exclusion')"
                )
            )
            .scalars()
            .all()
        )
    assert set(tables) == {"alembic_version"}
    assert functions == []
    command.upgrade(cfg, "head")
    engine.dispose()


def test_models_match_migrations(engine: Engine) -> None:
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diffs == []


def test_seeded_markets_are_exactly_the_confirmed_ones(db: Session) -> None:
    markets = db.scalars(select(Market)).all()
    assert {m.country_code for m in markets} == CONFIRMED_MARKETS
    assert all(m.status == "active" and m.decision_ref == "BD-004" for m in markets)
    assert "US" not in {m.country_code for m in markets}


def test_us_is_seeded_as_excluded_country(db: Session) -> None:
    us = db.get(Country, "US")
    assert us is not None and us.is_excluded
    assert us.exclusion_reason is not None and "BD-005" in us.exclusion_reason
    assert db.scalar(select(Country.code).where(Country.is_excluded, Country.code != "US")) is None


def test_curricula_are_exactly_the_confirmed_four_without_ib(db: Session) -> None:
    codes = set(db.scalars(select(Curriculum.code)))
    assert codes == {"IRISH", "SABIS", "AMERICAN", "BRITISH"}
    assert "IB" not in codes
    british = db.scalar(select(Curriculum).where(Curriculum.code == "BRITISH"))
    assert british is not None
    boards = set(db.scalars(select(ExamBoard.code).where(ExamBoard.curriculum_id == british.id)))
    quals = set(db.scalars(select(Qualification.code).where(Qualification.curriculum_id == british.id)))
    assert boards == {"CAMBRIDGE", "PEARSON_EDEXCEL", "AQA", "OCR"}
    assert quals == {"IGCSE", "GCSE", "AS", "A_LEVEL"}


def test_permission_catalogue_matches_code(db: Session) -> None:
    assert {p.key: p.description for p in db.scalars(select(Permission))} == PERMISSIONS
    for key, (_name, _description, perms) in ROLES.items():
        role = db.scalar(select(Role).where(Role.key == key))
        assert role is not None, key
        assert set(db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == role.id))) == set(
            perms
        )
    assert set(db.scalars(select(Role.key))) == set(ROLES)


def _expect_db_error(db: Session, sql: str, fragment: str) -> None:
    with pytest.raises(DBAPIError) as info, db.begin_nested():
        db.execute(text(sql))
    assert fragment in str(info.value)


def test_us_market_is_impossible(db: Session) -> None:
    _expect_db_error(
        db,
        "INSERT INTO markets (id, country_code, name, status, default_timezone) "
        "VALUES (gen_random_uuid(), 'US', 'United States', 'active', 'America/New_York')",
        "can never be a market",
    )


def test_us_cannot_be_un_excluded(db: Session) -> None:
    _expect_db_error(db, "UPDATE countries SET is_excluded = false WHERE code = 'US'", "must stay excluded")


def test_country_with_market_cannot_be_excluded(db: Session) -> None:
    _expect_db_error(db, "UPDATE countries SET is_excluded = true WHERE code = 'AE'", "has a market")


def _seed_consent(db: Session) -> None:
    account = Account(display_name="Append-only test", created_by=SYSTEM_ACTOR.principal_id)
    db.add(account)
    db.flush()
    contact = Contact(account_id=account.id, role="guardian", first_name="Test", created_by=SYSTEM_ACTOR.principal_id)
    db.add(contact)
    db.flush()
    db.add(
        Consent(
            contact_id=contact.id,
            purpose="marketing_email",
            status="granted",
            legal_basis="consent",
            source="staff_logged",
            evidence={"note": "test"},
            captured_by=SYSTEM_ACTOR.principal_id,
        )
    )
    db.flush()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_log SET action = 'x'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
        "UPDATE consents SET status = 'withdrawn'",
        "DELETE FROM consents",
        "TRUNCATE consents CASCADE",
    ],
)
def test_append_only_tables(db: Session, sql: str) -> None:
    audit.record(db, SYSTEM_ACTOR, "test_event", "test", "1", {"a": 1})
    _seed_consent(db)
    _expect_db_error(db, sql, "append-only")


def test_audit_chain_verifies(db: Session) -> None:
    for i in range(3):
        audit.record(db, SYSTEM_ACTOR, "test_event", "test", str(i), {"i": i, "text": 'quote " and | pipe'})
    db.flush()
    result = audit.verify_chain(db)
    assert result.ok and result.rows_checked >= 3


def _tamper(db: Session, sql: str) -> None:
    """Simulate a superuser bypassing the append-only triggers."""
    db.execute(text("SET LOCAL session_replication_role = replica"))
    db.execute(text(sql))
    db.execute(text("SET LOCAL session_replication_role = origin"))


def test_audit_chain_detects_edits(db: Session) -> None:
    for i in range(3):
        audit.record(db, SYSTEM_ACTOR, "test_event", "test", str(i), {"i": i})
    db.flush()
    target = db.execute(text("SELECT max(chain_seq) - 1 FROM audit_log")).scalar_one()
    _tamper(db, f"UPDATE audit_log SET changes = '{{\"i\": 99}}' WHERE chain_seq = {target}")
    result = audit.verify_chain(db)
    assert not result.ok and result.first_broken_chain_seq == target
    assert result.reason == "row content does not match its hash"


def test_audit_chain_detects_removed_rows(db: Session) -> None:
    for i in range(3):
        audit.record(db, SYSTEM_ACTOR, "test_event", "test", str(i), {"i": i})
    db.flush()
    target = db.execute(text("SELECT max(chain_seq) - 1 FROM audit_log")).scalar_one()
    _tamper(db, f"DELETE FROM audit_log WHERE chain_seq = {target}")
    result = audit.verify_chain(db)
    assert not result.ok
