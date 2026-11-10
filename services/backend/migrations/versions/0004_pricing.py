"""Phase 2a: pricing catalogue. Loads the 13 supplied price books (91 entries) as locked drafts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10 13:30:00

The figures below are transcribed from the brief (S1) exactly as listed in docs/05 v0.2, and a test
compares them with an independent reading of that register. Nothing here is active: every version
is a draft with figures "supplied, unverified", tax treatment unknown and figures locked
(BD-017, BD-019, BD-020). Corrections are loaded later as new versions; these rows are never edited
(BD-015, BD-018, ADR-14). The two USD books get no market assignment (Q-MKT-01; never the US: BD-006).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NS = uuid.UUID("6f1d3a52-2c3e-4b8e-9a51-6d1f2b7c9e10")  # same namespace as 0001/0002
SYSTEM_PRINCIPAL_ID = "00000000-0000-7000-8000-000000000001"
SOURCE = "Project initialisation brief (S1), pricing sheets; transcribed in docs/05 v0.2"
RECEIVED = "2026-11-09"


def _sid(kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


def _hours(*rows: tuple[int, int]) -> list[tuple[str, str, int, int]]:
    return [(f"{q}H", f"{q}h", q, total) for q, total in rows]


def _classes(*rows: tuple[int, int]) -> list[tuple[str, str, int, int]]:
    return [(f"{q}C", f"{q} classes", q, total) for q, total in rows]


# (code, name, currency, plan_type, tier_label, unit_type, market, assignment ref, needs relationship
#  confirmation, unit definition ref, extra summary, entries[(package_code, display, quantity, total_minor)])
BOOKS = [
    (
        "UK-GBP-TIER-A",
        "United Kingdom, GBP, Tier A",
        "GBP",
        "standard",
        "Tier A",
        "hour",
        "GB",
        "BD-012",
        False,
        "S1: sheet in hours",
        "",
        _hours((15, 28500), (20, 36000), (30, 51000), (40, 64000), (60, 84000), (80, 96000), (100, 100000)),
    ),
    (
        "UK-GBP-TIER-B",
        "United Kingdom, GBP, Tier B",
        "GBP",
        "standard",
        "Tier B",
        "hour",
        "GB",
        "BD-012",
        False,
        "S1: sheet in hours",
        "",
        _hours(
            (15, 31500),
            (20, 40000),
            (30, 57000),
            (40, 72000),
            (60, 102000),
            (100, 150000),
            (150, 195000),
            (200, 220000),
        ),
    ),
    (
        "USD-SCHEDULE-A",
        "USD Schedule A (market unconfirmed)",
        "USD",
        "standard",
        "Schedule A",
        "hour",
        None,
        None,
        False,
        "S1: sheet in hours",
        " Market assignment unconfirmed (Q-MKT-01); never the US (BD-006).",
        _hours(
            (10, 26000),
            (20, 48000),
            (30, 66000),
            (50, 100000),
            (70, 119000),
            (100, 150000),
            (150, 195000),
            (200, 220000),
        ),
    ),
    (
        "USD-SCHEDULE-B",
        "USD Schedule B (market unconfirmed)",
        "USD",
        "standard",
        "Schedule B",
        "hour",
        None,
        None,
        False,
        "S1: sheet in hours",
        " Market assignment unconfirmed (Q-MKT-01); never the US (BD-006).",
        _hours((10, 29000), (20, 54000), (30, 75000), (40, 92000), (60, 120000), (100, 170000), (200, 280000)),
    ),
    (
        "AE-AED-TIER-A",
        "United Arab Emirates, AED, Tier A",
        "AED",
        "standard",
        "Tier A",
        "hour",
        "AE",
        "BD-013",
        False,
        "S1: sheet in hours",
        "",
        _hours(
            (15, 105000),
            (20, 130000),
            (30, 180000),
            (40, 228000),
            (60, 318000),
            (100, 490000),
            (150, 660000),
            (200, 760000),
        ),
    ),
    (
        "AE-AED-TIER-B",
        "United Arab Emirates, AED, Tier B",
        "AED",
        "standard",
        "Tier B",
        "hour",
        "AE",
        "BD-013",
        False,
        "S1: sheet in hours",
        "",
        _hours(
            (15, 112500),
            (20, 140000),
            (30, 195000),
            (40, 240000),
            (60, 330000),
            (100, 490000),
            (150, 660000),
            (200, 760000),
        ),
    ),
    (
        "SA-SAR",
        "Saudi Arabia, SAR",
        "SAR",
        "standard",
        None,
        "hour",
        "SA",
        "S1",
        False,
        "S1: sheet in hours",
        "",
        _hours(
            (15, 112500),
            (20, 140000),
            (30, 195000),
            (40, 240000),
            (60, 330000),
            (100, 490000),
            (150, 660000),
            (200, 760000),
        ),
    ),
    (
        "QA-QAR",
        "Qatar, QAR",
        "QAR",
        "standard",
        None,
        "hour",
        "QA",
        "S1",
        False,
        "S1: sheet in hours",
        "",
        _hours(
            (15, 105000),
            (20, 130000),
            (30, 180000),
            (40, 228000),
            (60, 318000),
            (100, 490000),
            (150, 660000),
            (200, 760000),
        ),
    ),
    (
        "MY-MYR",
        "Malaysia, MYR",
        "MYR",
        "standard",
        None,
        "hour",
        "MY",
        "S1",
        False,
        "S1: sheet in hours",
        " Mixt confirmed the totals were mathematically corrected (BD-015); whether this set is the corrected one "
        "is open (Q-PRC-21). A different set would be loaded as version 2 (correction).",
        _hours(
            (15, 117000),
            (20, 148000),
            (30, 210000),
            (40, 264000),
            (60, 348000),
            (100, 540000),
            (150, 735000),
            (200, 900000),
        ),
    ),
    (
        "IE-EUR-SCHEDULE-A",
        "Ireland, EUR, Schedule A",
        "EUR",
        "standard",
        "Schedule A",
        "class",
        "IE",
        "BD-014",
        True,
        "BD-011: 1 class = 1 hour",
        " Relationship to Schedule B open (Q-PRC-03).",
        _classes((15, 31500), (20, 40000), (30, 54000), (40, 64000), (60, 90000), (80, 104000), (100, 120000)),
    ),
    (
        "IE-EUR-SCHEDULE-B",
        "Ireland, EUR, Schedule B",
        "EUR",
        "standard",
        "Schedule B",
        "hour",
        "IE",
        "BD-014",
        True,
        "S1: sheet in hours",
        " Relationship to Schedule A open (Q-PRC-03).",
        _hours((10, 25000), (20, 48000), (30, 66000), (50, 100000), (75, 135000), (100, 150000)),
    ),
    (
        "HK-HKD-STANDARD",
        "Hong Kong, HKD, Standard",
        "HKD",
        "standard",
        "Standard",
        "hour",
        "HK",
        "BD-016",
        False,
        "S1: sheet in hours",
        "",
        _hours((10, 320000), (20, 600000), (30, 840000), (40, 1000000)),
    ),
    (
        "HK-HKD-PREMIUM",
        "Hong Kong, HKD, Premium",
        "HKD",
        "premium",
        "Premium",
        "hour",
        "HK",
        "BD-016",
        False,
        "S1: sheet in hours",
        "",
        _hours((60, 1380000), (100, 1800000), (150, 2400000), (200, 2800000)),
    ),
]

# Benefits as supplied (docs/05 §4). Definitions only, except the Hong Kong ones, which are attached to
# their version as drafts. Nothing is approved, so nothing can be claimed with a price yet.
BENEFITS = [
    # (code, name, kind, supplied scope, attach to book)
    ("GEN-PAST-PAPERS", "Past papers and curated study resources", "benefit", "General (supplied so far)", None),
    ("GEN-ACADEMIC-SUPPORT", "Dedicated academic support", "benefit", "General (supplied so far)", None),
    ("GEN-FLEXIBLE-SCHEDULING", "Flexible scheduling", "benefit", "General (supplied so far)", None),
    (
        "GEN-NO-EXPIRY-APPLICABLE",
        "No expiry on purchased hours in applicable packages",
        "policy",
        "General (supplied so far)",
        None,
    ),
    ("GEN-MULTI-SUBJECT", "Multiple subjects across grades", "benefit", "General (supplied so far)", None),
    ("GEN-FAMILY-SHARING", "Sibling/family hour sharing", "policy", "General (supplied so far)", None),
    ("IE-VALIDITY-18M", "18-month validity", "policy", "Ireland packages", None),
    ("IE-PAUSE-RESUME", "Pause and resume", "policy", "Ireland packages", None),
    ("IE-RECORDED-SESSIONS", "Recorded sessions", "benefit", "Ireland packages", None),
    ("IE-PROGRESS-REPORTS", "Fortnightly progress reports", "benefit", "Ireland packages", None),
    ("IE-PARENT-CALLS", "Parent check-in calls", "benefit", "Ireland packages", None),
    ("IE-WHATSAPP-COORDINATOR", "Dedicated WhatsApp coordinator", "benefit", "Ireland packages", None),
    ("IE-IRISH-TUTORS", "Irish-curriculum-trained tutors", "benefit", "Ireland packages", None),
    (
        "IE-REFUND-OR-SWAP",
        "Advertised first-paid-session refund or free tutor swap guarantee",
        "policy",
        "Ireland packages",
        None,
    ),
    ("HKS-NO-EXPIRY", "No expiry", "policy", "HK Standard", "HK-HKD-STANDARD"),
    ("HKS-FOUR-SUBJECTS", "Up to four subjects", "policy", "HK Standard", "HK-HKD-STANDARD"),
    ("HKS-FAMILY-SHARING", "Family sharing", "policy", "HK Standard", "HK-HKD-STANDARD"),
    ("HKS-FLEXIBLE-SCHEDULING", "Flexible scheduling", "benefit", "HK Standard", "HK-HKD-STANDARD"),
    ("HKP-RECORDED-SESSIONS", "Recorded sessions", "benefit", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-UNLIMITED-SUBJECTS", "Unlimited subjects across grades", "policy", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-NO-EXPIRY", "No expiry", "policy", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-PARENT-TEACHER", "Bi-monthly parent-teacher consultations", "benefit", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-PROGRESS-REPORTS", "Bi-weekly progress reports", "benefit", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-ACADEMIC-SUPPORT", "Academic support team", "benefit", "HK Premium", "HK-HKD-PREMIUM"),
    ("HKP-TEACHER-CHAT", "Teacher chat access", "benefit", "HK Premium", "HK-HKD-PREMIUM"),
]

NEW_PERMISSIONS = {
    "pricing.read": "View price books, versions, entries and their activation checklist (internal only)",
    "pricing.version.submit": "Submit a price-book version for review",
    "pricing.version.approve": "Approve or reject a price-book version (not one you submitted)",
    "pricing.version.activate": "Activate or retire a price-book version (the activation gate must pass)",
    "pricing.version.confirm_figures": "Record Mixt's confirmation of a version's figures (needs a decision reference)",
    "pricing.version.tax": "Record a version's tax treatment (needs a decision reference)",
    "pricing.version.correct": "Load a correction as a new version (the original is kept unchanged)",
    "pricing.assignments.manage": "Confirm or revoke a price book's market assignment (needs a decision reference)",
    "pricing.benefits.approve": "Approve benefits attached to a price-book version",
    "pricing.tier.select": "Choose a customer's tier or schedule between valid options, with a reason",
    "pricing.options.read": "Look up the package options a customer can be offered (active pricing only)",
}
_MANAGE = [k for k in NEW_PERMISSIONS if k not in ("pricing.tier.select", "pricing.options.read")]
NEW_GRANTS = {
    "owner": list(NEW_PERMISSIONS),
    # Admins create sales staff, and can only grant what they hold (identity service).
    "admin": ["pricing.read", "pricing.tier.select", "pricing.options.read"],
    "pricing_manager": [*_MANAGE, "pricing.options.read"],
    "sales_manager": ["pricing.read", "pricing.tier.select", "pricing.options.read"],
    "sales_rep": ["pricing.options.read"],
    "finance": ["pricing.read", "pricing.version.tax"],
}

TRIGGERS = """
CREATE FUNCTION pricing_guard_entry_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v record;
BEGIN
  SELECT status, figures_locked INTO v FROM price_book_versions WHERE id = NEW.price_book_version_id;
  IF v.figures_locked OR v.status <> 'draft' THEN
    RAISE EXCEPTION 'price book version % is locked: supplied figures are never changed; load a correction as a new version',
      NEW.price_book_version_id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_price_book_entries_insert_guard BEFORE INSERT ON price_book_entries
  FOR EACH ROW EXECUTE FUNCTION pricing_guard_entry_insert();
CREATE TRIGGER trg_price_book_entries_append_only BEFORE UPDATE OR DELETE ON price_book_entries
  FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_price_book_entries_no_truncate BEFORE TRUNCATE ON price_book_entries
  FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();

CREATE FUNCTION pricing_guard_versions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'price book versions are never deleted: pricing history is kept' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.figures_locked AND NOT NEW.figures_locked THEN
    RAISE EXCEPTION 'locked figures cannot be unlocked' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.price_book_id <> OLD.price_book_id OR NEW.version_no <> OLD.version_no
     OR NEW.change_type <> OLD.change_type OR NEW.supersedes_version_id IS DISTINCT FROM OLD.supersedes_version_id
     OR NEW.source_document <> OLD.source_document OR NEW.source_received_on <> OLD.source_received_on
     OR NEW.session_minutes_per_unit <> OLD.session_minutes_per_unit OR NEW.created_by <> OLD.created_by THEN
    RAISE EXCEPTION 'a price book version''s identity, source and unit never change: create a new version'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('superseded', 'retired', 'rejected') AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'price book version % is closed (%)', OLD.id, OLD.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_price_book_versions_guard BEFORE UPDATE OR DELETE ON price_book_versions
  FOR EACH ROW EXECUTE FUNCTION pricing_guard_versions();

CREATE FUNCTION pricing_guard_books() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'price books are never deleted: archive them instead' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.code <> OLD.code OR NEW.currency_code <> OLD.currency_code OR NEW.unit_type <> OLD.unit_type
     OR NEW.plan_type <> OLD.plan_type THEN
    RAISE EXCEPTION 'a price book''s code, currency, unit and plan type never change: create a new price book'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_price_books_guard BEFORE UPDATE OR DELETE ON price_books
  FOR EACH ROW EXECUTE FUNCTION pricing_guard_books();
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_price_books_guard ON price_books;
DROP FUNCTION IF EXISTS pricing_guard_books();
DROP TRIGGER IF EXISTS trg_price_book_versions_guard ON price_book_versions;
DROP FUNCTION IF EXISTS pricing_guard_versions();
DROP TRIGGER IF EXISTS trg_price_book_entries_no_truncate ON price_book_entries;
DROP TRIGGER IF EXISTS trg_price_book_entries_append_only ON price_book_entries;
DROP TRIGGER IF EXISTS trg_price_book_entries_insert_guard ON price_book_entries;
DROP FUNCTION IF EXISTS pricing_guard_entry_insert();
"""


def _seed() -> None:
    conn = op.get_bind()
    for code, name, currency, plan, tier, unit, market, ref, relationship, unit_ref, extra, entries in BOOKS:
        book_id, version_id = _sid("price_book", code), _sid("price_book_version", f"{code}:1")
        conn.execute(
            sa.text(
                "INSERT INTO price_books (id, code, name, currency_code, plan_type, tier_label, unit_type, audience) "
                "VALUES (:id, :code, :name, :cur, :plan, :tier, :unit, 'public')"
            ),
            {"id": book_id, "code": code, "name": name, "cur": currency, "plan": plan, "tier": tier, "unit": unit},
        )
        conn.execute(
            sa.text(
                "INSERT INTO price_book_versions (id, price_book_id, version_no, status, change_type, "
                "figures_confirmation, unit_definition_ref, session_minutes_per_unit, source_document, "
                "source_received_on, change_summary, created_by) VALUES (:id, :book, 1, 'draft', 'initial', "
                "'supplied_unverified', :unit_ref, 60, :source, :received, :summary, :system)"
            ),
            {
                "id": version_id,
                "book": book_id,
                "unit_ref": unit_ref,
                "source": SOURCE,
                "received": RECEIVED,
                "summary": "Initial load of the figures supplied by Mixt, unchanged." + extra,
                "system": SYSTEM_PRINCIPAL_ID,
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO price_book_entries (id, price_book_version_id, package_code, display_name, quantity, "
                "package_total_minor, sort_order) VALUES (:id, :version, :pkg, :display, :qty, :total, :sort)"
            ),
            [
                {
                    "id": _sid("price_book_entry", f"{code}:1:{pkg}"),
                    "version": version_id,
                    "pkg": pkg,
                    "display": display,
                    "qty": qty,
                    "total": total,
                    "sort": i,
                }
                for i, (pkg, display, qty, total) in enumerate(entries)
            ],
        )
        conn.execute(sa.text("UPDATE price_book_versions SET figures_locked = true WHERE id = :id"), {"id": version_id})
        if market:
            conn.execute(
                sa.text(
                    "INSERT INTO price_book_market_assignments (id, price_book_id, market_id, assignment_status, "
                    "decision_ref, requires_relationship_confirmation, confirmed_by, confirmed_at, notes) "
                    "VALUES (:id, :book, :market, 'confirmed', :ref, :rel, :system, now(), :notes)"
                ),
                {
                    "id": _sid("price_book_market", f"{code}:{market}"),
                    "book": book_id,
                    "market": _sid("market", market),
                    "ref": ref,
                    "rel": relationship,
                    "system": SYSTEM_PRINCIPAL_ID,
                    "notes": "Sheet supplied for this market in the brief (S1).",
                },
            )
    for i, (code, name, kind, scope, book) in enumerate(BENEFITS):
        definition_id = _sid("benefit_definition", code)
        conn.execute(
            sa.text(
                "INSERT INTO benefit_definitions (id, code, name, kind, supplied_scope, source_document) "
                "VALUES (:id, :code, :name, :kind, :scope, :source)"
            ),
            {"id": definition_id, "code": code, "name": name, "kind": kind, "scope": scope, "source": SOURCE},
        )
        if book:
            conn.execute(
                sa.text(
                    "INSERT INTO package_benefits (id, price_book_version_id, benefit_definition_id, "
                    "customer_facing_text, sort_order, status) VALUES (:id, :version, :definition, :text, :sort, 'draft')"
                ),
                {
                    "id": _sid("package_benefit", f"{book}:1:{code}"),
                    "version": _sid("price_book_version", f"{book}:1"),
                    "definition": definition_id,
                    "text": name,
                    "sort": i,
                },
            )
    conn.execute(
        sa.text("INSERT INTO permissions (key, description) VALUES (:k, :d)"),
        [{"k": k, "d": d} for k, d in NEW_PERMISSIONS.items()],
    )
    for role, perms in NEW_GRANTS.items():
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:r, :p)"),
            [{"r": _sid("role", role), "p": p} for p in perms],
        )


def _unseed() -> None:
    conn = op.get_bind()
    keys = list(NEW_PERMISSIONS)
    conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_key = ANY(:keys)"), {"keys": keys})
    conn.execute(sa.text("DELETE FROM permissions WHERE key = ANY(:keys)"), {"keys": keys})


def _create_tables() -> None:
    op.create_table(
        "benefit_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("supplied_scope", sa.Text(), nullable=False),
        sa.Column("source_document", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('benefit','policy')", name=op.f("ck_benefit_definitions_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benefit_definitions")),
        sa.UniqueConstraint("code", name=op.f("uq_benefit_definitions_code")),
    )
    op.create_table(
        "price_books",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("plan_type", sa.String(length=16), nullable=False),
        sa.Column("tier_label", sa.Text(), nullable=True),
        sa.Column("unit_type", sa.String(length=8), nullable=False),
        sa.Column("audience", sa.String(length=16), server_default=sa.text("'public'"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("audience IN ('public','restricted')", name=op.f("ck_price_books_audience")),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name=op.f("ck_price_books_code_format")),
        sa.CheckConstraint(
            "plan_type IN ('standard', 'premium', 'promotional', 'custom')", name=op.f("ck_price_books_plan_type")
        ),
        sa.CheckConstraint("unit_type IN ('hour', 'class')", name=op.f("ck_price_books_unit_type")),
        sa.ForeignKeyConstraint(
            ["currency_code"], ["currencies.code"], name=op.f("fk_price_books_currency_code_currencies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_books")),
        sa.UniqueConstraint("code", name=op.f("uq_price_books_code")),
    )
    op.create_table(
        "price_book_market_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_status", sa.String(length=16), nullable=False),
        sa.Column("is_market_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("requires_relationship_confirmation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("relationship_confirmed_ref", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "assignment_status <> 'confirmed' OR (decision_ref IS NOT NULL AND confirmed_by IS NOT NULL)",
            name=op.f("ck_price_book_market_assignments_confirmation_complete"),
        ),
        sa.CheckConstraint(
            "assignment_status IN ('unconfirmed','confirmed','revoked')",
            name=op.f("ck_price_book_market_assignments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["principals.id"], name=op.f("fk_price_book_market_assignments_confirmed_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_price_book_market_assignments_market_id_markets")
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"],
            ["price_books.id"],
            name=op.f("fk_price_book_market_assignments_price_book_id_price_books"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_book_market_assignments")),
        sa.UniqueConstraint(
            "price_book_id", "market_id", name=op.f("uq_price_book_market_assignments_price_book_id_market_id")
        ),
    )
    op.create_index(
        op.f("ix_price_book_market_assignments_market_id"), "price_book_market_assignments", ["market_id"], unique=False
    )
    op.create_index(
        op.f("ix_price_book_market_assignments_price_book_id"),
        "price_book_market_assignments",
        ["price_book_id"],
        unique=False,
    )
    op.create_table(
        "price_book_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("change_type", sa.String(length=16), server_default=sa.text("'initial'"), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("figures_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "figures_confirmation",
            sa.String(length=24),
            server_default=sa.text("'supplied_unverified'"),
            nullable=False,
        ),
        sa.Column("figures_confirmation_ref", sa.Text(), nullable=True),
        sa.Column("figures_confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("figures_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unit_definition_ref", sa.Text(), nullable=True),
        sa.Column("session_minutes_per_unit", sa.SmallInteger(), server_default=sa.text("60"), nullable=False),
        sa.Column("tax_treatment", sa.String(length=16), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("tax_treatment_ref", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_document", sa.Text(), nullable=False),
        sa.Column("source_received_on", sa.Date(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("second_approved_by", sa.Uuid(), nullable=True),
        sa.Column("second_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(figures_confirmation = 'confirmed') = (figures_confirmation_ref IS NOT NULL)",
            name=op.f("ck_price_book_versions_confirmation_ref"),
        ),
        sa.CheckConstraint(
            "(tax_treatment = 'unknown') = (tax_treatment_ref IS NULL)", name=op.f("ck_price_book_versions_tax_ref")
        ),
        sa.CheckConstraint(
            "change_type <> 'correction' OR supersedes_version_id IS NOT NULL",
            name=op.f("ck_price_book_versions_correction_lineage"),
        ),
        sa.CheckConstraint(
            "change_type IN ('initial', 'correction', 'price_change')", name=op.f("ck_price_book_versions_change_type")
        ),
        sa.CheckConstraint(
            "figures_confirmation IN ('supplied_unverified','confirmed')",
            name=op.f("ck_price_book_versions_figures_confirmation"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'active', 'superseded', 'retired', 'rejected')",
            name=op.f("ck_price_book_versions_status"),
        ),
        sa.CheckConstraint(
            "tax_treatment IN ('unknown', 'inclusive', 'exclusive', 'not_applicable')",
            name=op.f("ck_price_book_versions_tax_treatment"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name=op.f("ck_price_book_versions_dates"),
        ),
        sa.CheckConstraint(
            "session_minutes_per_unit BETWEEN 15 AND 240", name=op.f("ck_price_book_versions_minutes_per_unit")
        ),
        sa.CheckConstraint("version_no >= 1", name=op.f("ck_price_book_versions_version_no")),
        sa.CheckConstraint(
            "status <> 'active' OR (figures_locked AND figures_confirmation = 'confirmed' AND tax_treatment <> 'unknown' AND unit_definition_ref IS NOT NULL AND approved_by IS NOT NULL AND content_hash IS NOT NULL AND activated_by IS NOT NULL)",
            name=op.f("ck_price_book_versions_active_requirements"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved','active','superseded') OR approved_by IS NOT NULL",
            name=op.f("ck_price_book_versions_approval_recorded"),
        ),
        sa.CheckConstraint(
            "second_approved_by IS NULL OR (approved_by IS NOT NULL AND second_approved_by <> approved_by)",
            name=op.f("ck_price_book_versions_two_different_approvers"),
        ),
        sa.ForeignKeyConstraint(
            ["activated_by"], ["principals.id"], name=op.f("fk_price_book_versions_activated_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["principals.id"], name=op.f("fk_price_book_versions_approved_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["principals.id"], name=op.f("fk_price_book_versions_created_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["figures_confirmed_by"],
            ["principals.id"],
            name=op.f("fk_price_book_versions_figures_confirmed_by_principals"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"], ["price_books.id"], name=op.f("fk_price_book_versions_price_book_id_price_books")
        ),
        sa.ForeignKeyConstraint(
            ["second_approved_by"], ["principals.id"], name=op.f("fk_price_book_versions_second_approved_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["principals.id"], name=op.f("fk_price_book_versions_submitted_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["price_book_versions.id"],
            name=op.f("fk_price_book_versions_supersedes_version_id_price_book_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_book_versions")),
        sa.UniqueConstraint(
            "price_book_id", "version_no", name=op.f("uq_price_book_versions_price_book_id_version_no")
        ),
    )
    op.create_index(
        "uq_price_book_versions_one_active",
        "price_book_versions",
        ["price_book_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "price_book_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("price_book_version_id", sa.Uuid(), nullable=False),
        sa.Column("package_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("package_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("advertised_unit_rate_minor", sa.BigInteger(), nullable=True),
        sa.Column(
            "derived_unit_rate_minor",
            sa.BigInteger(),
            sa.Computed("CAST(round(package_total_minor / quantity) AS bigint)", persisted=True),
            nullable=False,
        ),
        sa.Column("is_purchasable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "advertised_unit_rate_minor IS NULL OR advertised_unit_rate_minor > 0",
            name=op.f("ck_price_book_entries_advertised"),
        ),
        sa.CheckConstraint("package_total_minor > 0", name=op.f("ck_price_book_entries_package_total")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_price_book_entries_quantity")),
        sa.ForeignKeyConstraint(
            ["price_book_version_id"],
            ["price_book_versions.id"],
            name=op.f("fk_price_book_entries_price_book_version_id_price_book_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_book_entries")),
        sa.UniqueConstraint(
            "price_book_version_id",
            "package_code",
            name=op.f("uq_price_book_entries_price_book_version_id_package_code"),
        ),
        sa.UniqueConstraint(
            "price_book_version_id", "quantity", name=op.f("uq_price_book_entries_price_book_version_id_quantity")
        ),
    )
    op.create_index(
        op.f("ix_price_book_entries_price_book_version_id"),
        "price_book_entries",
        ["price_book_version_id"],
        unique=False,
    )
    op.create_table(
        "package_benefits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("price_book_version_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_entry_id", sa.Uuid(), nullable=True),
        sa.Column("benefit_definition_id", sa.Uuid(), nullable=False),
        sa.Column("customer_facing_text", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("copied_from_id", sa.Uuid(), nullable=True),
        sa.Column("cross_market_copy_approved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(status = 'approved') = (approved_by IS NOT NULL)", name=op.f("ck_package_benefits_approval")
        ),
        sa.CheckConstraint("status IN ('draft','approved')", name=op.f("ck_package_benefits_status")),
        sa.CheckConstraint(
            "copied_from_id IS NULL OR cross_market_copy_approved_by IS NOT NULL",
            name=op.f("ck_package_benefits_cross_market_copy"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["principals.id"], name=op.f("fk_package_benefits_approved_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["benefit_definition_id"],
            ["benefit_definitions.id"],
            name=op.f("fk_package_benefits_benefit_definition_id_benefit_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["copied_from_id"],
            ["package_benefits.id"],
            name=op.f("fk_package_benefits_copied_from_id_package_benefits"),
        ),
        sa.ForeignKeyConstraint(
            ["cross_market_copy_approved_by"],
            ["principals.id"],
            name=op.f("fk_package_benefits_cross_market_copy_approved_by_principals"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_entry_id"],
            ["price_book_entries.id"],
            name=op.f("fk_package_benefits_price_book_entry_id_price_book_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_version_id"],
            ["price_book_versions.id"],
            name=op.f("fk_package_benefits_price_book_version_id_price_book_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_benefits")),
        sa.UniqueConstraint(
            "price_book_version_id",
            "benefit_definition_id",
            name=op.f("uq_package_benefits_price_book_version_id_benefit_definition_id"),
        ),
    )
    op.create_index(
        op.f("ix_package_benefits_price_book_version_id"), "package_benefits", ["price_book_version_id"], unique=False
    )
    op.create_table(
        "pricing_tier_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("plan_type", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("selected_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('active','replaced','revoked')", name=op.f("ck_pricing_tier_selections_status")),
        sa.CheckConstraint("length(btrim(reason)) >= 5", name=op.f("ck_pricing_tier_selections_reason")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_pricing_tier_selections_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_pricing_tier_selections_market_id_markets")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_pricing_tier_selections_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"], ["price_books.id"], name=op.f("fk_pricing_tier_selections_price_book_id_price_books")
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["pricing_tier_selections.id"],
            name=op.f("fk_pricing_tier_selections_replaced_by_id_pricing_tier_selections"),
        ),
        sa.ForeignKeyConstraint(
            ["selected_by_user_id"], ["users.id"], name=op.f("fk_pricing_tier_selections_selected_by_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_tier_selections")),
    )
    op.create_index(
        op.f("ix_pricing_tier_selections_account_id"), "pricing_tier_selections", ["account_id"], unique=False
    )
    op.create_index(
        "uq_pricing_tier_selections_one_active",
        "pricing_tier_selections",
        ["account_id", "opportunity_id", "market_id", "plan_type"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        postgresql_nulls_not_distinct=True,
    )


def _drop_tables() -> None:
    op.drop_index(
        "uq_pricing_tier_selections_one_active",
        table_name="pricing_tier_selections",
        postgresql_where=sa.text("status = 'active'"),
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index(op.f("ix_pricing_tier_selections_account_id"), table_name="pricing_tier_selections")
    op.drop_table("pricing_tier_selections")
    op.drop_index(op.f("ix_package_benefits_price_book_version_id"), table_name="package_benefits")
    op.drop_table("package_benefits")
    op.drop_index(op.f("ix_price_book_entries_price_book_version_id"), table_name="price_book_entries")
    op.drop_table("price_book_entries")
    op.drop_index(
        "uq_price_book_versions_one_active",
        table_name="price_book_versions",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table("price_book_versions")
    op.drop_index(op.f("ix_price_book_market_assignments_price_book_id"), table_name="price_book_market_assignments")
    op.drop_index(op.f("ix_price_book_market_assignments_market_id"), table_name="price_book_market_assignments")
    op.drop_table("price_book_market_assignments")
    op.drop_table("price_books")
    op.drop_table("benefit_definitions")


def upgrade() -> None:
    _create_tables()
    op.execute(TRIGGERS)
    _seed()


def downgrade() -> None:
    _unseed()
    op.execute(DROP_TRIGGERS)
    _drop_tables()
