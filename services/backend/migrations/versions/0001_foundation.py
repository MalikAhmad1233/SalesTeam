"""Foundation: identity, reference data, settings, audit log and core CRM (Phase 1a)

Revision ID: 0001
Revises:
Create Date: 2026-11-10 07:48:51.096915
"""

from __future__ import annotations

import csv
import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------------------------
# Hand-written parts of this migration: extensions, sequences, integrity triggers and seed data.
# Seed data is frozen here on purpose: later catalogue changes get their own migrations.
# ---------------------------------------------------------------------------------------------

SYSTEM_PRINCIPAL_ID = "00000000-0000-7000-8000-000000000001"
_NS = uuid.UUID("6f1d3a52-2c3e-4b8e-9a51-6d1f2b7c9e10")


def _sid(kind: str, key: str) -> str:
    """Deterministic ids for seeded rows, so every environment has the same ids."""
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


# BD-004 (confirmed 2026-11-09): the 13 markets Mixt operates in. The US is NOT a market (BD-005).
MARKETS = [
    ("AE", "United Arab Emirates", "Asia/Dubai"),
    ("QA", "Qatar", "Asia/Qatar"),
    ("KW", "Kuwait", "Asia/Kuwait"),
    ("SA", "Saudi Arabia", "Asia/Riyadh"),
    ("OM", "Oman", "Asia/Muscat"),
    ("BH", "Bahrain", "Asia/Bahrain"),
    ("MY", "Malaysia", "Asia/Kuala_Lumpur"),
    ("HK", "Hong Kong", "Asia/Hong_Kong"),
    ("SG", "Singapore", "Asia/Singapore"),
    ("ID", "Indonesia", "Asia/Jakarta"),
    ("KR", "South Korea", "Asia/Seoul"),
    ("GB", "United Kingdom", "Europe/London"),
    ("IE", "Ireland", "Europe/Dublin"),
]

# ISO 4217 facts (code, name, minor units, display prefix). Currencies are reference data, not prices.
CURRENCIES = [
    ("GBP", "Pound sterling", 2, "£"),
    ("EUR", "Euro", 2, "€"),
    ("USD", "US dollar", 2, "USD "),
    ("AED", "UAE dirham", 2, "AED "),
    ("SAR", "Saudi riyal", 2, "SAR "),
    ("QAR", "Qatari riyal", 2, "QAR "),
    ("MYR", "Malaysian ringgit", 2, "RM "),
    ("HKD", "Hong Kong dollar", 2, "HKD "),
    ("KWD", "Kuwaiti dinar", 3, "KWD "),
    ("OMR", "Omani rial", 3, "OMR "),
    ("BHD", "Bahraini dinar", 3, "BHD "),
    ("SGD", "Singapore dollar", 2, "SGD "),
    ("IDR", "Indonesian rupiah", 2, "IDR "),
    ("KRW", "South Korean won", 0, "KRW "),
]

LANGUAGES = [
    ("en", "English"),
    ("ar", "Arabic"),
    ("ms", "Malay"),
    ("id", "Indonesian"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
]

# BD-007: the four confirmed curriculum categories. IB is deliberately absent (BD-008).
CURRICULA = [
    ("IRISH", "Irish Curriculum"),
    ("SABIS", "SABIS Curriculum"),
    ("AMERICAN", "American Curriculum"),
    ("BRITISH", "British Curriculum"),
]
# BD-009: British exam boards and qualifications as supplied. Combinations taught: OPEN (Q-ACA-02).
BRITISH_BOARDS = [("CAMBRIDGE", "Cambridge"), ("PEARSON_EDEXCEL", "Pearson Edexcel"), ("AQA", "AQA"), ("OCR", "OCR")]
BRITISH_QUALIFICATIONS = [("IGCSE", "IGCSE"), ("GCSE", "GCSE"), ("AS", "AS Level"), ("A_LEVEL", "A Level")]

PERMISSIONS = {
    "users.read": "View staff users",
    "users.manage": "Create users, change their status and roles",
    "teams.manage": "Create teams and manage membership",
    "reference.read": "View reference data (markets, currencies, curricula)",
    "reference.markets.manage": "Add or change markets (excluded countries are always blocked)",
    "reference.curricula.manage": "Add curricula, boards or qualifications (requires a decision-log reference)",
    "settings.read": "View settings and outstanding decisions",
    "settings.change.owner": "Change settings reserved for the Owner",
    "settings.change.pricing": "Change pricing settings",
    "settings.change.sales": "Change sales settings",
    "settings.change.admin": "Change operations settings",
    "settings.change.finance": "Change finance settings",
    "audit.read": "View the audit log",
    "audit.verify": "Verify audit-log integrity",
    "crm.accounts.read": "View accounts the user has access to",
    "crm.accounts.read_all": "View all accounts regardless of owner (optionally limited to a market)",
    "crm.accounts.create": "Create accounts",
    "crm.accounts.update": "Update accounts the user has access to",
    "crm.accounts.assign_owner": "Change an account's owner",
    "crm.market.confirm": "Confirm an account's pricing market",
    "crm.consents.record": "Record consent given or withdrawn",
    "crm.students.manage": "Create and update students and their academic profiles",
    "crm.students.learning_needs.read": "Read restricted learning-needs notes",
    "crm.students.learning_needs.write": "Write restricted learning-needs notes",
}
_CRM = [
    "crm.accounts.read",
    "crm.accounts.create",
    "crm.accounts.update",
    "crm.market.confirm",
    "crm.consents.record",
    "crm.students.manage",
]
ROLES = {
    "owner": ("Owner / Super Admin", "Everything, including security settings and role management", list(PERMISSIONS)),
    "admin": (
        "Admin (Operations)",
        "Users, reference data, operations settings, all CRM records",
        [
            "users.read",
            "users.manage",
            "teams.manage",
            "reference.read",
            "reference.markets.manage",
            "settings.read",
            "settings.change.admin",
            "audit.read",
            "audit.verify",
            *_CRM,
            "crm.accounts.read_all",
            "crm.accounts.assign_owner",
        ],
    ),
    "pricing_manager": (
        "Pricing Manager",
        "Pricing configuration and approvals",
        ["reference.read", "settings.read", "settings.change.pricing"],
    ),
    "sales_manager": (
        "Sales Manager",
        "All accounts in their markets/teams, assignments, sales settings",
        [
            "users.read",
            "reference.read",
            "settings.read",
            "settings.change.sales",
            *_CRM,
            "crm.accounts.read_all",
            "crm.accounts.assign_owner",
            "crm.students.learning_needs.read",
            "crm.students.learning_needs.write",
        ],
    ),
    "sales_rep": (
        "Sales Representative",
        "Own accounts and the unassigned pool",
        ["reference.read", "settings.read", *_CRM],
    ),
    "finance": (
        "Finance",
        "Invoices and payments (from Phase 6), finance settings",
        ["reference.read", "settings.read", "settings.change.finance", "crm.accounts.read", "crm.accounts.read_all"],
    ),
    "tutor_coordinator": (
        "Tutor Coordinator",
        "Students, tutors and trials",
        [
            "reference.read",
            "settings.read",
            "crm.accounts.read",
            "crm.accounts.read_all",
            "crm.students.manage",
            "crm.students.learning_needs.read",
            "crm.students.learning_needs.write",
        ],
    ),
    "analyst": (
        "Analyst (read-only)",
        "Reports; no personal-data access by default",
        ["reference.read", "settings.read"],
    ),
}

TRIGGERS_SQL = r"""
-- DB-01: no market may be created for an excluded country (the US, BD-005).
CREATE FUNCTION markets_reject_excluded_country() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM countries WHERE code = NEW.country_code AND is_excluded) THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation', CONSTRAINT = 'market_country_excluded',
      MESSAGE = format('country %s is excluded and can never be a market', NEW.country_code);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_markets_reject_excluded_country BEFORE INSERT OR UPDATE OF country_code ON markets
  FOR EACH ROW EXECUTE FUNCTION markets_reject_excluded_country();

-- BD-005 defence in depth: the US exclusion cannot be switched off, and no excluded country may hold a market.
CREATE FUNCTION countries_guard_exclusion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.code = 'US' AND NOT NEW.is_excluded THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation', CONSTRAINT = 'us_must_stay_excluded',
      MESSAGE = 'The United States is not a target market (BD-005) and must stay excluded';
  END IF;
  IF NEW.is_excluded AND EXISTS (SELECT 1 FROM markets WHERE country_code = NEW.code) THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation', CONSTRAINT = 'market_country_excluded',
      MESSAGE = format('country %s has a market and cannot be excluded without removing it', NEW.code);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_countries_guard_exclusion BEFORE INSERT OR UPDATE ON countries
  FOR EACH ROW EXECUTE FUNCTION countries_guard_exclusion();

-- DB-09: append-only tables.
CREATE FUNCTION reject_modification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'append_only',
    MESSAGE = format('%s is append-only', TG_TABLE_NAME);
END $$;
CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_consents_append_only BEFORE UPDATE OR DELETE ON consents
  FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_consents_no_truncate BEFORE TRUNCATE ON consents
  FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();

-- Hash chain: each row's hash covers its content and the previous row's hash, so editing or
-- removing a row in the middle is detectable. The canonical form is a JSONB array (unambiguous).
CREATE FUNCTION audit_log_row_digest(prev bytea, r audit_log) RETURNS bytea LANGUAGE sql STABLE AS $$
  SELECT sha256(convert_to(jsonb_build_array(
    encode(prev, 'hex'), r.chain_seq,
    to_char(r.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
    r.actor_principal_id, r.actor_kind, r.approved_by_user_id, r.action, r.entity_type, r.entity_id,
    r.changes, host(r.ip), r.user_agent, r.correlation_id
  )::text, 'UTF8'))
$$;

CREATE FUNCTION audit_log_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  last_seq bigint;
  last_hash bytea;
BEGIN
  -- Serialise chain extension: held until the inserting transaction ends.
  PERFORM pg_advisory_xact_lock(7302410001);
  SELECT chain_seq, row_hash INTO last_seq, last_hash FROM audit_log ORDER BY chain_seq DESC LIMIT 1;
  NEW.chain_seq := coalesce(last_seq, 0) + 1;
  NEW.prev_hash := last_hash;
  NEW.occurred_at := coalesce(NEW.occurred_at, clock_timestamp());
  NEW.row_hash := audit_log_row_digest(last_hash, NEW);
  RETURN NEW;
END $$;
CREATE TRIGGER trg_audit_log_chain BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_chain();
"""

DROP_TRIGGERS_SQL = """
DROP FUNCTION IF EXISTS audit_log_chain() CASCADE;
DROP FUNCTION IF EXISTS audit_log_row_digest(bytea, audit_log) CASCADE;
DROP FUNCTION IF EXISTS reject_modification() CASCADE;
DROP FUNCTION IF EXISTS countries_guard_exclusion() CASCADE;
DROP FUNCTION IF EXISTS markets_reject_excluded_country() CASCADE;
"""


def _seed() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO principals (id, kind, display_name) VALUES (:id, 'system', 'Mixt AI system')"),
        {"id": SYSTEM_PRINCIPAL_ID},
    )

    countries_path = Path(__file__).resolve().parent.parent / "data" / "0001_countries.csv"
    with countries_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    conn.execute(
        sa.text(
            "INSERT INTO countries (code, name, is_excluded, exclusion_reason) VALUES (:code, :name, :ex, :reason)"
        ),
        [
            {
                "code": r["code"],
                "name": r["name"],
                "ex": r["code"] == "US",
                "reason": "BD-005: not a target, customer-acquisition or operating market"
                if r["code"] == "US"
                else None,
            }
            for r in rows
        ],
    )
    conn.execute(
        sa.text("INSERT INTO languages (code, name) VALUES (:c, :n)"), [{"c": c, "n": n} for c, n in LANGUAGES]
    )
    conn.execute(
        sa.text("INSERT INTO currencies (code, name, minor_units, display_prefix) VALUES (:c, :n, :m, :p)"),
        [{"c": c, "n": n, "m": m, "p": p} for c, n, m, p in CURRENCIES],
    )
    conn.execute(
        sa.text(
            "INSERT INTO markets (id, country_code, name, status, default_timezone, decision_ref) "
            "VALUES (:id, :cc, :name, 'active', :tz, 'BD-004')"
        ),
        [{"id": _sid("market", cc), "cc": cc, "name": name, "tz": tz} for cc, name, tz in MARKETS],
    )
    conn.execute(
        sa.text("INSERT INTO curricula (id, code, name, decision_ref) VALUES (:id, :code, :name, 'BD-007')"),
        [{"id": _sid("curriculum", code), "code": code, "name": name} for code, name in CURRICULA],
    )
    british = _sid("curriculum", "BRITISH")
    conn.execute(
        sa.text("INSERT INTO exam_boards (id, curriculum_id, code, name) VALUES (:id, :cid, :code, :name)"),
        [{"id": _sid("board", code), "cid": british, "code": code, "name": name} for code, name in BRITISH_BOARDS],
    )
    conn.execute(
        sa.text("INSERT INTO qualifications (id, curriculum_id, code, name) VALUES (:id, :cid, :code, :name)"),
        [
            {"id": _sid("qualification", code), "cid": british, "code": code, "name": name}
            for code, name in BRITISH_QUALIFICATIONS
        ],
    )
    conn.execute(
        sa.text("INSERT INTO permissions (key, description) VALUES (:k, :d)"),
        [{"k": k, "d": d} for k, d in PERMISSIONS.items()],
    )
    for key, (name, description, perms) in ROLES.items():
        role_id = _sid("role", key)
        conn.execute(
            sa.text("INSERT INTO roles (id, key, name, description) VALUES (:id, :key, :name, :d)"),
            {"id": role_id, "key": key, "name": name, "d": description},
        )
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:r, :p)"),
            [{"r": role_id, "p": p} for p in perms],
        )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE SEQUENCE account_number_seq START 1")
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("chain_seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False
        ),
        sa.Column("actor_principal_id", sa.Uuid(), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=True),
        sa.Column("row_hash", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sa.UniqueConstraint("chain_seq", name=op.f("uq_audit_log_chain_seq")),
    )
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_principal_id", "occurred_at"], unique=False)
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "countries",
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_excluded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_countries")),
    )
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("minor_units", sa.SmallInteger(), nullable=False),
        sa.Column("display_prefix", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("minor_units BETWEEN 0 AND 4", name=op.f("ck_currencies_minor_units")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_currencies")),
    )
    op.create_table(
        "curricula",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("decision_ref", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("decision_ref ~ '^BD-[0-9]{3}$'", name=op.f("ck_curricula_decision_ref_format")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curricula")),
        sa.UniqueConstraint("code", name=op.f("uq_curricula_code")),
    )
    op.create_table(
        "languages",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_languages")),
    )
    op.create_table(
        "permissions",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_permissions")),
    )
    op.create_table(
        "principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('user','agent','system','integration')", name=op.f("ck_principals_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principals")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_roles_key")),
    )
    op.create_table(
        "subjects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint("code", name=op.f("uq_subjects_code")),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("name", name=op.f("uq_teams_name")),
    )
    op.create_table(
        "exam_boards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["curriculum_id"], ["curricula.id"], name=op.f("fk_exam_boards_curriculum_id_curricula")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_boards")),
        sa.UniqueConstraint("curriculum_id", "code", name=op.f("uq_exam_boards_curriculum_id_code")),
    )
    op.create_table(
        "grade_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["curriculum_id"], ["curricula.id"], name=op.f("fk_grade_levels_curriculum_id_curricula")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grade_levels")),
        sa.UniqueConstraint("curriculum_id", "code", name=op.f("uq_grade_levels_curriculum_id_code")),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("default_timezone", sa.Text(), nullable=False),
        sa.Column("default_language", sa.Text(), nullable=True),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('planned','active','inactive')", name=op.f("ck_markets_status")),
        sa.ForeignKeyConstraint(["country_code"], ["countries.code"], name=op.f("fk_markets_country_code_countries")),
        sa.ForeignKeyConstraint(
            ["default_language"], ["languages.code"], name=op.f("fk_markets_default_language_languages")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_markets")),
        sa.UniqueConstraint("country_code", name=op.f("uq_markets_country_code")),
    )
    op.create_table(
        "qualifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["curriculum_id"], ["curricula.id"], name=op.f("fk_qualifications_curriculum_id_curricula")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qualifications")),
        sa.UniqueConstraint("curriculum_id", "code", name=op.f("uq_qualifications_curriculum_id_code")),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_key", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_key"], ["permissions.key"], name=op.f("fk_role_permissions_permission_key_permissions")
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_key", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('global','market','price_book','price_book_version','channel','agent','role','curriculum','pipeline','stage','data_type','deployment','action')",
            name=op.f("ck_system_settings_scope_type"),
        ),
        sa.CheckConstraint(
            "status <> 'confirmed' OR decision_ref ~ '^BD-[0-9]{3}$'",
            name=op.f("ck_system_settings_confirmed_needs_decision"),
        ),
        sa.CheckConstraint("status IN ('safe_default','confirmed')", name=op.f("ck_system_settings_status")),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["principals.id"], name=op.f("fk_system_settings_updated_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
        sa.UniqueConstraint(
            "key", "scope_type", "scope_id", name="uq_setting_scope", postgresql_nulls_not_distinct=True
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("mfa_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("timezone", sa.Text(), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column("locale", sa.Text(), server_default=sa.text("'en-GB'"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("status IN ('active','suspended','deactivated')", name=op.f("ck_users_status")),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name=op.f("fk_users_principal_id_principals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("principal_id", name=op.f("uq_users_principal_id")),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "account_number",
            sa.Text(),
            server_default=sa.text("'MX-' || lpad(nextval('account_number_seq')::text, 6, '0')"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), server_default=sa.text("'household'"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("country_of_residence", sa.String(length=2), nullable=True),
        sa.Column("market_id", sa.Uuid(), nullable=True),
        sa.Column("market_confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("market_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_confirmation_note", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("preferred_language", sa.Text(), nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=24), server_default=sa.text("'lead'"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("is_vip", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("kind IN ('household','institution')", name=op.f("ck_accounts_kind")),
        sa.CheckConstraint(
            "lifecycle_stage IN ('lead','prospect','customer','former_customer','disqualified','out_of_market')",
            name=op.f("ck_accounts_lifecycle_stage"),
        ),
        sa.CheckConstraint("status IN ('active','archived','anonymised')", name=op.f("ck_accounts_status")),
        sa.CheckConstraint(
            "(market_id IS NULL) = (market_confirmed_by IS NULL AND market_confirmed_at IS NULL)",
            name=op.f("ck_accounts_market_confirmation_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["country_of_residence"], ["countries.code"], name=op.f("fk_accounts_country_of_residence_countries")
        ),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"], name=op.f("fk_accounts_created_by_principals")),
        sa.ForeignKeyConstraint(
            ["market_confirmed_by"], ["principals.id"], name=op.f("fk_accounts_market_confirmed_by_principals")
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name=op.f("fk_accounts_market_id_markets")),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_accounts_owner_user_id_users")),
        sa.ForeignKeyConstraint(
            ["preferred_language"], ["languages.code"], name=op.f("fk_accounts_preferred_language_languages")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("account_number", name=op.f("uq_accounts_account_number")),
    )
    op.create_index(op.f("ix_accounts_market_id"), "accounts", ["market_id"], unique=False)
    op.create_index(op.f("ix_accounts_owner_user_id"), "accounts", ["owner_user_id"], unique=False)
    op.create_table(
        "board_qualification_offerings",
        sa.Column("exam_board_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("offered_by_mixt", sa.Boolean(), nullable=True),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["exam_board_id"],
            ["exam_boards.id"],
            name=op.f("fk_board_qualification_offerings_exam_board_id_exam_boards"),
        ),
        sa.ForeignKeyConstraint(
            ["qualification_id"],
            ["qualifications.id"],
            name=op.f("fk_board_qualification_offerings_qualification_id_qualifications"),
        ),
        sa.PrimaryKeyConstraint("exam_board_id", "qualification_id", name=op.f("pk_board_qualification_offerings")),
    )
    op.create_table(
        "principal_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["principals.id"], name=op.f("fk_principal_roles_granted_by_principals")
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name=op.f("fk_principal_roles_market_id_markets")),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_principal_roles_principal_id_principals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_principal_roles_role_id_roles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principal_roles")),
        sa.UniqueConstraint(
            "principal_id", "role_id", "market_id", name="uq_principal_role", postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index(op.f("ix_principal_roles_principal_id"), "principal_roles", ["principal_id"], unique=False)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_role", sa.String(length=16), server_default=sa.text("'member'"), nullable=False),
        sa.CheckConstraint("team_role IN ('member','lead')", name=op.f("ck_team_members_team_role")),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_members_team_id_teams"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_team_members_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_team_members")),
    )
    op.create_table(
        "user_mfa_factors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('totp')", name=op.f("ck_user_mfa_factors_kind")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_mfa_factors_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_mfa_factors")),
    )
    op.create_index(op.f("ix_user_mfa_factors_user_id"), "user_mfa_factors", ["user_id"], unique=False)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_hash", sa.LargeBinary(), nullable=False),
        sa.Column("mfa_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(
        "ix_user_sessions_active",
        "user_sessions",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("preferred_name", sa.Text(), nullable=True),
        sa.Column("relationship_to_students", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_decision_maker", sa.Boolean(), nullable=True),
        sa.Column("preferred_language", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("role IN ('guardian','payer','student','other')", name=op.f("ck_contacts_role")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_contacts_account_id_accounts")),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"], name=op.f("fk_contacts_created_by_principals")),
        sa.ForeignKeyConstraint(
            ["preferred_language"], ["languages.code"], name=op.f("fk_contacts_preferred_language_languages")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )
    op.create_index(op.f("ix_contacts_account_id"), "contacts", ["account_id"], unique=False)
    op.create_index(
        "uq_contacts_one_primary_per_account",
        "contacts",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND archived_at IS NULL"),
    )
    op.create_table(
        "contact_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('phone','whatsapp','email','instagram','web_chat')", name=op.f("ck_contact_points_kind")
        ),
        sa.CheckConstraint(
            "status IN ('active','bounced','invalid','opted_out')", name=op.f("ck_contact_points_status")
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name=op.f("fk_contact_points_contact_id_contacts")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["principals.id"], name=op.f("fk_contact_points_created_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_points")),
    )
    op.create_index(op.f("ix_contact_points_contact_id"), "contact_points", ["contact_id"], unique=False)
    op.create_index("ix_contact_points_kind_value", "contact_points", ["kind", "value"], unique=False)
    op.create_table(
        "students",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("preferred_name", sa.Text(), nullable=True),
        sa.Column("birth_year", sa.SmallInteger(), nullable=True),
        sa.Column("curriculum_id", sa.Uuid(), nullable=True),
        sa.Column("grade_level_id", sa.Uuid(), nullable=True),
        sa.Column("grade_text", sa.Text(), nullable=True),
        sa.Column("school_name", sa.Text(), nullable=True),
        sa.Column("country_of_study", sa.String(length=2), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column("learning_needs_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("learning_needs_key_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'prospective'"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("status IN ('prospective','active','paused','alumni')", name=op.f("ck_students_status")),
        sa.CheckConstraint(
            "(learning_needs_ciphertext IS NULL) = (learning_needs_key_id IS NULL)",
            name=op.f("ck_students_learning_needs_pair"),
        ),
        sa.CheckConstraint(
            "birth_year IS NULL OR birth_year BETWEEN 1950 AND 2100", name=op.f("ck_students_birth_year_range")
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_students_account_id_accounts")),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name=op.f("fk_students_contact_id_contacts")),
        sa.ForeignKeyConstraint(
            ["country_of_study"], ["countries.code"], name=op.f("fk_students_country_of_study_countries")
        ),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"], name=op.f("fk_students_created_by_principals")),
        sa.ForeignKeyConstraint(["curriculum_id"], ["curricula.id"], name=op.f("fk_students_curriculum_id_curricula")),
        sa.ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name=op.f("fk_students_grade_level_id_grade_levels")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_students")),
    )
    op.create_index(op.f("ix_students_account_id"), "students", ["account_id"], unique=False)
    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("contact_point_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("legal_basis", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("captured_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb", name=op.f("ck_consents_evidence_present")
        ),
        sa.CheckConstraint(
            "legal_basis IN ('consent','contract','legitimate_interests','legal_obligation')",
            name=op.f("ck_consents_legal_basis"),
        ),
        sa.CheckConstraint(
            "purpose IN ('service_messages','marketing_whatsapp','marketing_email','session_recording','ai_assisted_conversation','data_processing')",
            name=op.f("ck_consents_purpose"),
        ),
        sa.CheckConstraint(
            "source IN ('web_form','lead_ad_form','whatsapp_keyword','email_link','staff_logged','import')",
            name=op.f("ck_consents_source"),
        ),
        sa.CheckConstraint("status IN ('granted','withdrawn','denied')", name=op.f("ck_consents_status")),
        sa.ForeignKeyConstraint(["captured_by"], ["principals.id"], name=op.f("fk_consents_captured_by_principals")),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name=op.f("fk_consents_contact_id_contacts")),
        sa.ForeignKeyConstraint(
            ["contact_point_id"], ["contact_points.id"], name=op.f("fk_consents_contact_point_id_contact_points")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_contact_id"), "consents", ["contact_id"], unique=False)
    op.create_index("ix_consents_current", "consents", ["contact_id", "purpose", "captured_at"], unique=False)
    op.create_table(
        "scheduling_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("preferred_weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("preferred_windows", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lessons_per_week", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("preferred_session_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_scheduling_preferences_student_id_students"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduling_preferences")),
        sa.UniqueConstraint("student_id", name=op.f("uq_scheduling_preferences_student_id")),
    )
    op.create_table(
        "student_subjects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("subject_name", sa.Text(), nullable=False),
        sa.Column("exam_board_id", sa.Uuid(), nullable=True),
        sa.Column("qualification_id", sa.Uuid(), nullable=True),
        sa.Column("current_grade", sa.Text(), nullable=True),
        sa.Column("target_grade", sa.Text(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'interested'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('interested','active','completed','dropped')", name=op.f("ck_student_subjects_status")
        ),
        sa.ForeignKeyConstraint(
            ["exam_board_id"], ["exam_boards.id"], name=op.f("fk_student_subjects_exam_board_id_exam_boards")
        ),
        sa.ForeignKeyConstraint(
            ["qualification_id"],
            ["qualifications.id"],
            name=op.f("fk_student_subjects_qualification_id_qualifications"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name=op.f("fk_student_subjects_student_id_students"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name=op.f("fk_student_subjects_subject_id_subjects")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_subjects")),
    )
    op.create_index(op.f("ix_student_subjects_student_id"), "student_subjects", ["student_id"], unique=False)
    op.create_table(
        "student_exams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("student_subject_id", sa.Uuid(), nullable=True),
        sa.Column("exam_board_id", sa.Uuid(), nullable=True),
        sa.Column("qualification_id", sa.Uuid(), nullable=True),
        sa.Column("exam_session", sa.Text(), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("paper_code", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('customer','staff','ai_extracted')", name=op.f("ck_student_exams_source")),
        sa.ForeignKeyConstraint(
            ["exam_board_id"], ["exam_boards.id"], name=op.f("fk_student_exams_exam_board_id_exam_boards")
        ),
        sa.ForeignKeyConstraint(
            ["qualification_id"], ["qualifications.id"], name=op.f("fk_student_exams_qualification_id_qualifications")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name=op.f("fk_student_exams_student_id_students"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["student_subject_id"],
            ["student_subjects.id"],
            name=op.f("fk_student_exams_student_subject_id_student_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_exams")),
    )
    op.create_index(op.f("ix_student_exams_student_id"), "student_exams", ["student_id"], unique=False)
    op.execute(TRIGGERS_SQL)
    _seed()
    # ### end Alembic commands ###


def downgrade() -> None:
    op.execute(DROP_TRIGGERS_SQL)
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_student_exams_student_id"), table_name="student_exams")
    op.drop_table("student_exams")
    op.drop_index(op.f("ix_student_subjects_student_id"), table_name="student_subjects")
    op.drop_table("student_subjects")
    op.drop_table("scheduling_preferences")
    op.drop_index("ix_consents_current", table_name="consents")
    op.drop_index(op.f("ix_consents_contact_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index(op.f("ix_students_account_id"), table_name="students")
    op.drop_table("students")
    op.drop_index("ix_contact_points_kind_value", table_name="contact_points")
    op.drop_index(op.f("ix_contact_points_contact_id"), table_name="contact_points")
    op.drop_table("contact_points")
    op.drop_index(
        "uq_contacts_one_primary_per_account",
        table_name="contacts",
        postgresql_where=sa.text("is_primary AND archived_at IS NULL"),
    )
    op.drop_index(op.f("ix_contacts_account_id"), table_name="contacts")
    op.drop_table("contacts")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_index("ix_user_sessions_active", table_name="user_sessions", postgresql_where=sa.text("revoked_at IS NULL"))
    op.drop_table("user_sessions")
    op.drop_index(op.f("ix_user_mfa_factors_user_id"), table_name="user_mfa_factors")
    op.drop_table("user_mfa_factors")
    op.drop_table("team_members")
    op.drop_index(op.f("ix_principal_roles_principal_id"), table_name="principal_roles")
    op.drop_table("principal_roles")
    op.drop_table("board_qualification_offerings")
    op.drop_index(op.f("ix_accounts_owner_user_id"), table_name="accounts")
    op.drop_index(op.f("ix_accounts_market_id"), table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")
    op.drop_table("system_settings")
    op.drop_table("role_permissions")
    op.drop_table("qualifications")
    op.drop_table("markets")
    op.drop_table("grade_levels")
    op.drop_table("exam_boards")
    op.drop_table("teams")
    op.drop_table("subjects")
    op.drop_table("roles")
    op.drop_table("principals")
    op.drop_table("permissions")
    op.drop_table("languages")
    op.drop_table("curricula")
    op.drop_table("currencies")
    op.drop_table("countries")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_table("audit_log")
    op.execute("DROP SEQUENCE IF EXISTS account_number_seq")
    # ### end Alembic commands ###
