"""Phase 2b: pricing import, rules, confidential customer pricing, promotions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10 14:05:00

Nothing here is switched on: no rule, special price or promotion exists, and promotions cannot be
activated while the setting ``promotions.enabled`` is false (Q-PRC-05).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NS = uuid.UUID("6f1d3a52-2c3e-4b8e-9a51-6d1f2b7c9e10")


def _sid(kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


NEW_PERMISSIONS = {
    "pricing.import": "Upload a pricing sheet and create draft versions or new price books from it",
    "pricing.rules.manage": "Write draft pricing rules and attach approved rules to a market assignment",
    "pricing.rules.approve": "Approve a pricing rule (not one you wrote)",
    "pricing.special.view": "See confidential customer pricing",
    "pricing.special.request": "Request confidential pricing for a customer",
    "pricing.special.approve": "Approve or revoke confidential customer pricing (not one you requested)",
    "pricing.promotions.manage": "Draft and submit promotions",
    "pricing.promotions.approve": "Approve, activate or cancel promotions (not one you submitted)",
}
_PM = list(NEW_PERMISSIONS)
NEW_GRANTS = {
    "owner": _PM,
    "pricing_manager": _PM,
    "sales_manager": ["pricing.special.view", "pricing.special.request"],
    # Admins create sales managers and can only grant what they hold.
    "admin": ["pricing.special.view", "pricing.special.request"],
}

TRIGGERS = """
CREATE FUNCTION pricing_guard_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'approved pricing rules are never deleted: retire them' USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status <> 'draft' AND (NEW.definition IS DISTINCT FROM OLD.definition OR NEW.kind <> OLD.kind
     OR NEW.code <> OLD.code OR NEW.rule_version <> OLD.rule_version) THEN
    RAISE EXCEPTION 'an approved pricing rule never changes: write a new version' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'retired' AND NEW.status <> 'retired' THEN
    RAISE EXCEPTION 'a retired pricing rule stays retired' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_pricing_rules_guard BEFORE UPDATE OR DELETE ON pricing_rules
  FOR EACH ROW EXECUTE FUNCTION pricing_guard_rules();

CREATE FUNCTION pricing_guard_promotions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'promotions are never deleted: cancel them' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status <> 'draft' AND (NEW.kind <> OLD.kind OR NEW.value IS DISTINCT FROM OLD.value
     OR NEW.starts_at <> OLD.starts_at OR NEW.ends_at <> OLD.ends_at OR NEW.stackable <> OLD.stackable
     OR NEW.eligibility_rule_id IS DISTINCT FROM OLD.eligibility_rule_id OR NEW.code <> OLD.code) THEN
    RAISE EXCEPTION 'a submitted promotion''s terms never change: cancel it and create a new one'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('expired', 'cancelled') AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'promotion % is closed (%)', OLD.code, OLD.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_promotions_guard BEFORE UPDATE OR DELETE ON promotions
  FOR EACH ROW EXECUTE FUNCTION pricing_guard_promotions();
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_promotions_guard ON promotions;
DROP FUNCTION IF EXISTS pricing_guard_promotions();
DROP TRIGGER IF EXISTS trg_pricing_rules_guard ON pricing_rules;
DROP FUNCTION IF EXISTS pricing_guard_rules();
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
        "pricing_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_version_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "status IN ('validated','invalid','applied','discarded')", name=op.f("ck_pricing_import_batches_status")
        ),
        sa.ForeignKeyConstraint(
            ["applied_by"], ["principals.id"], name=op.f("fk_pricing_import_batches_applied_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["principals.id"], name=op.f("fk_pricing_import_batches_uploaded_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_import_batches")),
    )
    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(status = 'draft') = (approved_by IS NULL)", name=op.f("ck_pricing_rules_approval")),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name=op.f("ck_pricing_rules_code_format")),
        sa.CheckConstraint("kind IN ('eligibility','minimum_purchase')", name=op.f("ck_pricing_rules_kind")),
        sa.CheckConstraint("status IN ('draft','approved','retired')", name=op.f("ck_pricing_rules_status")),
        sa.CheckConstraint("approved_by IS NULL OR approved_by <> created_by", name=op.f("ck_pricing_rules_four_eyes")),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["principals.id"], name=op.f("fk_pricing_rules_approved_by_principals")
        ),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"], name=op.f("fk_pricing_rules_created_by_principals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_rules")),
        sa.UniqueConstraint("code", "rule_version", name=op.f("uq_pricing_rules_code_rule_version")),
    )
    op.create_table(
        "pricing_import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["pricing_import_batches.id"],
            name=op.f("fk_pricing_import_rows_batch_id_pricing_import_batches"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_import_rows")),
        sa.UniqueConstraint("batch_id", "row_no", name=op.f("uq_pricing_import_rows_batch_id_row_no")),
    )
    op.create_index(op.f("ix_pricing_import_rows_batch_id"), "pricing_import_rows", ["batch_id"], unique=False)
    op.create_table(
        "promotions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("eligibility_rule_id", sa.Uuid(), nullable=True),
        sa.Column("stackable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("max_per_account", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name=op.f("ck_promotions_code_format")),
        sa.CheckConstraint("kind IN ('percent_off','amount_off','bonus_units')", name=op.f("ck_promotions_kind")),
        sa.CheckConstraint(
            "status IN ('draft','in_review','approved','active','expired','cancelled')",
            name=op.f("ck_promotions_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved','active','expired') OR approved_by IS NOT NULL",
            name=op.f("ck_promotions_approval_recorded"),
        ),
        sa.CheckConstraint("approved_by IS NULL OR approved_by <> submitted_by", name=op.f("ck_promotions_four_eyes")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_promotions_must_expire")),
        sa.CheckConstraint("max_per_account >= 1", name=op.f("ck_promotions_max_per_account")),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions >= 1", name=op.f("ck_promotions_max_redemptions")
        ),
        sa.ForeignKeyConstraint(
            ["activated_by"], ["principals.id"], name=op.f("fk_promotions_activated_by_principals")
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["principals.id"], name=op.f("fk_promotions_approved_by_principals")),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"], name=op.f("fk_promotions_created_by_principals")),
        sa.ForeignKeyConstraint(
            ["eligibility_rule_id"], ["pricing_rules.id"], name=op.f("fk_promotions_eligibility_rule_id_pricing_rules")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["principals.id"], name=op.f("fk_promotions_submitted_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotions")),
        sa.UniqueConstraint("code", name=op.f("uq_promotions_code")),
    )
    op.create_table(
        "customer_pricing_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), server_default=sa.text("'pending_approval'"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status <> 'active' OR approved_by IS NOT NULL",
            name=op.f("ck_customer_pricing_assignments_active_approved"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_approval','active','rejected','revoked','expired')",
            name=op.f("ck_customer_pricing_assignments_status"),
        ),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by", name=op.f("ck_customer_pricing_assignments_four_eyes")
        ),
        sa.CheckConstraint("length(btrim(reason)) >= 5", name=op.f("ck_customer_pricing_assignments_reason")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name=op.f("ck_customer_pricing_assignments_dates")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_customer_pricing_assignments_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_customer_pricing_assignments_approved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"], ["principals.id"], name=op.f("fk_customer_pricing_assignments_closed_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"],
            ["price_books.id"],
            name=op.f("fk_customer_pricing_assignments_price_book_id_price_books"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name=op.f("fk_customer_pricing_assignments_requested_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_pricing_assignments")),
    )
    op.create_index(
        op.f("ix_customer_pricing_assignments_account_id"), "customer_pricing_assignments", ["account_id"], unique=False
    )
    op.create_table(
        "promotion_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("price_book_version_id", sa.Uuid(), nullable=True),
        sa.Column("price_book_entry_id", sa.Uuid(), nullable=True),
        sa.Column("market_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "price_book_version_id IS NOT NULL OR price_book_entry_id IS NOT NULL",
            name=op.f("ck_promotion_targets_has_target"),
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name=op.f("fk_promotion_targets_market_id_markets")),
        sa.ForeignKeyConstraint(
            ["price_book_entry_id"],
            ["price_book_entries.id"],
            name=op.f("fk_promotion_targets_price_book_entry_id_price_book_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["price_book_version_id"],
            ["price_book_versions.id"],
            name=op.f("fk_promotion_targets_price_book_version_id_price_book_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], name=op.f("fk_promotion_targets_promotion_id_promotions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotion_targets")),
    )
    op.create_index(op.f("ix_promotion_targets_promotion_id"), "promotion_targets", ["promotion_id"], unique=False)
    op.add_column("price_book_market_assignments", sa.Column("eligibility_rule_id", sa.Uuid(), nullable=True))
    op.add_column("price_book_market_assignments", sa.Column("minimum_purchase_rule_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_price_book_market_assignments_eligibility_rule_id_pricing_rules"),
        "price_book_market_assignments",
        "pricing_rules",
        ["eligibility_rule_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_price_book_market_assignments_minimum_purchase_rule_id_pricing_rules"),
        "price_book_market_assignments",
        "pricing_rules",
        ["minimum_purchase_rule_id"],
        ["id"],
    )


def _schema_down() -> None:
    op.drop_constraint(
        op.f("fk_price_book_market_assignments_minimum_purchase_rule_id_pricing_rules"),
        "price_book_market_assignments",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_price_book_market_assignments_eligibility_rule_id_pricing_rules"),
        "price_book_market_assignments",
        type_="foreignkey",
    )
    op.drop_column("price_book_market_assignments", "minimum_purchase_rule_id")
    op.drop_column("price_book_market_assignments", "eligibility_rule_id")
    op.drop_index(op.f("ix_promotion_targets_promotion_id"), table_name="promotion_targets")
    op.drop_table("promotion_targets")
    op.drop_index(op.f("ix_customer_pricing_assignments_account_id"), table_name="customer_pricing_assignments")
    op.drop_table("customer_pricing_assignments")
    op.drop_table("promotions")
    op.drop_index(op.f("ix_pricing_import_rows_batch_id"), table_name="pricing_import_rows")
    op.drop_table("pricing_import_rows")
    op.drop_table("pricing_rules")
    op.drop_table("pricing_import_batches")


def upgrade() -> None:
    _schema_up()
    op.execute(TRIGGERS)
    _seed()


def downgrade() -> None:
    _unseed()
    op.execute(DROP_TRIGGERS)
    _schema_down()
