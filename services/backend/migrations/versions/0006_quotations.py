"""Phase 2c: quotations, lines, approvals and promotion redemptions

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10 14:40:00
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NS = uuid.UUID("6f1d3a52-2c3e-4b8e-9a51-6d1f2b7c9e10")


def _sid(kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


NEW_PERMISSIONS = {
    "quotations.read": "View quotations of customers the user can see",
    "quotations.manage": "Prepare quotations, submit them for approval, issue approved ones and record the outcome",
    "quotations.approve": "Approve a quotation (sales approval; not one you prepared)",
    "quotations.approve_discount": "Approve a discount on a quotation (pricing approval; not one you prepared)",
}
NEW_GRANTS = {
    "owner": list(NEW_PERMISSIONS),
    # Admins create sales staff and can only grant what they hold.
    "admin": ["quotations.read", "quotations.manage", "quotations.approve"],
    "sales_manager": ["quotations.read", "quotations.manage", "quotations.approve"],
    "sales_rep": ["quotations.read", "quotations.manage"],
    "pricing_manager": ["quotations.approve_discount"],
    "finance": ["quotations.read"],
}

TRIGGERS = """
CREATE SEQUENCE quotation_number_seq START 1;

CREATE FUNCTION quotations_guard_lines() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
  SELECT status INTO s FROM quotations WHERE id = COALESCE(NEW.quotation_id, OLD.quotation_id);
  IF s IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'quotation lines can only change while the quotation is a draft' USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.quotation_id <> OLD.quotation_id THEN
    RAISE EXCEPTION 'a line cannot move to another quotation' USING ERRCODE = 'check_violation';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER trg_quotation_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON quotation_lines
  FOR EACH ROW EXECUTE FUNCTION quotations_guard_lines();

CREATE FUNCTION quotations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'quotations are never deleted: cancel or revise them' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.snapshot_hash IS NOT NULL AND (
       NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash OR NEW.pricing_snapshot IS DISTINCT FROM OLD.pricing_snapshot
    OR NEW.subtotal_minor <> OLD.subtotal_minor OR NEW.promotion_total_minor <> OLD.promotion_total_minor
    OR NEW.discount_total_minor <> OLD.discount_total_minor OR NEW.total_minor <> OLD.total_minor
    OR NEW.currency_code IS DISTINCT FROM OLD.currency_code OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
    OR NEW.account_id <> OLD.account_id OR NEW.market_id <> OLD.market_id
    OR NEW.quote_number <> OLD.quote_number OR NEW.revision_no <> OLD.revision_no) THEN
    RAISE EXCEPTION 'an approved quotation never changes: create a revision' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('accepted', 'declined', 'expired', 'superseded', 'cancelled') AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'quotation % revision % is closed (%)', OLD.quote_number, OLD.revision_no, OLD.status
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_quotations_guard BEFORE UPDATE OR DELETE ON quotations
  FOR EACH ROW EXECUTE FUNCTION quotations_guard();
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_quotations_guard ON quotations;
DROP FUNCTION IF EXISTS quotations_guard();
DROP TRIGGER IF EXISTS trg_quotation_lines_guard ON quotation_lines;
DROP FUNCTION IF EXISTS quotations_guard_lines();
DROP SEQUENCE IF EXISTS quotation_number_seq;
"""


def _seed() -> None:
    conn = op.get_bind()
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


def _schema_up() -> None:
    op.create_table(
        "quotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quote_number", sa.Text(), nullable=False),
        sa.Column("revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("parent_quotation_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=24), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("subtotal_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("promotion_total_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("discount_total_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_treatment", sa.String(length=16), nullable=True),
        sa.Column("discount_reason", sa.Text(), nullable=True),
        sa.Column("required_approvals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_hash", sa.Text(), nullable=True),
        sa.Column("prepared_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("issued_to_contact_id", sa.Uuid(), nullable=True),
        sa.Column("issued_via", sa.String(length=24), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_recorded_by", sa.Uuid(), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'issued', 'accepted', 'declined', 'expired', 'superseded', 'cancelled')",
            name=op.f("ck_quotations_status"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending_approval','cancelled') OR (snapshot_hash IS NOT NULL AND valid_until IS NOT NULL)",
            name=op.f("ck_quotations_approved_has_snapshot"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('issued','accepted','declined') OR (issued_at IS NOT NULL AND issued_to_contact_id IS NOT NULL)",
            name=op.f("ck_quotations_issued_complete"),
        ),
        sa.CheckConstraint(
            "discount_total_minor >= 0 AND promotion_total_minor >= 0", name=op.f("ck_quotations_non_negative")
        ),
        sa.CheckConstraint("revision_no >= 1", name=op.f("ck_quotations_revision_no")),
        sa.CheckConstraint(
            "total_minor = subtotal_minor - promotion_total_minor - discount_total_minor",
            name=op.f("ck_quotations_totals"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_quotations_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["currency_code"], ["currencies.code"], name=op.f("fk_quotations_currency_code_currencies")
        ),
        sa.ForeignKeyConstraint(["issued_by"], ["principals.id"], name=op.f("fk_quotations_issued_by_principals")),
        sa.ForeignKeyConstraint(
            ["issued_to_contact_id"], ["contacts.id"], name=op.f("fk_quotations_issued_to_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name=op.f("fk_quotations_market_id_markets")),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], name=op.f("fk_quotations_opportunity_id_opportunities")
        ),
        sa.ForeignKeyConstraint(
            ["outcome_recorded_by"], ["principals.id"], name=op.f("fk_quotations_outcome_recorded_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["parent_quotation_id"], ["quotations.id"], name=op.f("fk_quotations_parent_quotation_id_quotations")
        ),
        sa.ForeignKeyConstraint(["prepared_by"], ["principals.id"], name=op.f("fk_quotations_prepared_by_principals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotations")),
        sa.UniqueConstraint("quote_number", "revision_no", name=op.f("uq_quotations_quote_number_revision_no")),
    )
    op.create_index(op.f("ix_quotations_account_id"), "quotations", ["account_id"], unique=False)
    op.create_index(op.f("ix_quotations_opportunity_id"), "quotations", ["opportunity_id"], unique=False)
    op.create_table(
        "promotion_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_promotion_redemptions_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], name=op.f("fk_promotion_redemptions_promotion_id_promotions")
        ),
        sa.ForeignKeyConstraint(
            ["quotation_id"], ["quotations.id"], name=op.f("fk_promotion_redemptions_quotation_id_quotations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotion_redemptions")),
        sa.UniqueConstraint(
            "promotion_id", "quotation_id", name=op.f("uq_promotion_redemptions_promotion_id_quotation_id")
        ),
    )
    op.create_index(
        op.f("ix_promotion_redemptions_promotion_id"), "promotion_redemptions", ["promotion_id"], unique=False
    )
    op.create_table(
        "quotation_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("capacity", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("capacity IN ('sales','pricing')", name=op.f("ck_quotation_approvals_capacity")),
        sa.CheckConstraint("decision IN ('approve','reject')", name=op.f("ck_quotation_approvals_decision")),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], name=op.f("fk_quotation_approvals_decided_by_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["quotation_id"], ["quotations.id"], name=op.f("fk_quotation_approvals_quotation_id_quotations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotation_approvals")),
        sa.UniqueConstraint(
            "quotation_id", "decided_by_user_id", name=op.f("uq_quotation_approvals_quotation_id_decided_by_user_id")
        ),
    )
    op.create_index(op.f("ix_quotation_approvals_quotation_id"), "quotation_approvals", ["quotation_id"], unique=False)
    op.create_table(
        "quotation_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quotation_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.SmallInteger(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_code", sa.Text(), nullable=False),
        sa.Column("price_book_version_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_version_no", sa.Integer(), nullable=False),
        sa.Column("price_book_entry_id", sa.Uuid(), nullable=False),
        sa.Column("package_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("plan_type", sa.String(length=16), nullable=False),
        sa.Column("tier_label", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("unit_type", sa.String(length=8), nullable=False),
        sa.Column("session_minutes_per_unit", sa.SmallInteger(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("list_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("promotion_id", sa.Uuid(), nullable=True),
        sa.Column("promotion_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("promotion_discount_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("bonus_units", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("discount_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("final_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("special_assignment_id", sa.Uuid(), nullable=True),
        sa.Column("tier_selection_id", sa.Uuid(), nullable=True),
        sa.Column("benefits_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "discount_minor >= 0 AND promotion_discount_minor >= 0", name=op.f("ck_quotation_lines_non_negative")
        ),
        sa.CheckConstraint(
            "final_total_minor = list_total_minor - promotion_discount_minor - discount_minor",
            name=op.f("ck_quotation_lines_final_total"),
        ),
        sa.CheckConstraint("final_total_minor > 0", name=op.f("ck_quotation_lines_positive_total")),
        sa.ForeignKeyConstraint(
            ["currency_code"], ["currencies.code"], name=op.f("fk_quotation_lines_currency_code_currencies")
        ),
        sa.ForeignKeyConstraint(
            ["price_book_entry_id"],
            ["price_book_entries.id"],
            name=op.f("fk_quotation_lines_price_book_entry_id_price_book_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"], ["price_books.id"], name=op.f("fk_quotation_lines_price_book_id_price_books")
        ),
        sa.ForeignKeyConstraint(
            ["price_book_version_id"],
            ["price_book_versions.id"],
            name=op.f("fk_quotation_lines_price_book_version_id_price_book_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], name=op.f("fk_quotation_lines_promotion_id_promotions")
        ),
        sa.ForeignKeyConstraint(
            ["quotation_id"], ["quotations.id"], name=op.f("fk_quotation_lines_quotation_id_quotations")
        ),
        sa.ForeignKeyConstraint(
            ["special_assignment_id"],
            ["customer_pricing_assignments.id"],
            name=op.f("fk_quotation_lines_special_assignment_id_customer_pricing_assignments"),
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name=op.f("fk_quotation_lines_student_id_students")),
        sa.ForeignKeyConstraint(
            ["tier_selection_id"],
            ["pricing_tier_selections.id"],
            name=op.f("fk_quotation_lines_tier_selection_id_pricing_tier_selections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotation_lines")),
        sa.UniqueConstraint("quotation_id", "line_no", name=op.f("uq_quotation_lines_quotation_id_line_no")),
    )
    op.create_index(op.f("ix_quotation_lines_quotation_id"), "quotation_lines", ["quotation_id"], unique=False)


def _schema_down() -> None:
    op.drop_index(op.f("ix_quotation_lines_quotation_id"), table_name="quotation_lines")
    op.drop_table("quotation_lines")
    op.drop_index(op.f("ix_quotation_approvals_quotation_id"), table_name="quotation_approvals")
    op.drop_table("quotation_approvals")
    op.drop_index(op.f("ix_promotion_redemptions_promotion_id"), table_name="promotion_redemptions")
    op.drop_table("promotion_redemptions")
    op.drop_index(op.f("ix_quotations_opportunity_id"), table_name="quotations")
    op.drop_index(op.f("ix_quotations_account_id"), table_name="quotations")
    op.drop_table("quotations")


def upgrade() -> None:
    _schema_up()
    op.execute(TRIGGERS)
    _seed()


def downgrade() -> None:
    _unseed()
    op.execute(DROP_TRIGGERS)
    _schema_down()
