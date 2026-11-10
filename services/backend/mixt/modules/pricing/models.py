"""Pricing tables (docs/02 §8, docs/04). Private to the pricing module.

Integrity rules enforced by the database (migration 0004), not only by code:
* entries of a version whose figures are locked, or that is no longer a draft, cannot be inserted,
  changed or deleted (supplied figures are never silently changed: BD-015, BD-018, ADR-14);
* a locked version cannot be unlocked and its source, unit and lineage cannot change;
* a price book's code, currency, unit and plan type never change;
* at most one active version per price book;
* a correction must point at the version it corrects.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, uuid_pk

PLAN_TYPES = ("standard", "premium", "promotional", "custom")
UNIT_TYPES = ("hour", "class")
VERSION_STATUSES = ("draft", "in_review", "approved", "active", "superseded", "retired", "rejected")
CHANGE_TYPES = ("initial", "correction", "price_change")
TAX_TREATMENTS = ("unknown", "inclusive", "exclusive", "not_applicable")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PriceBook(Base):
    __tablename__ = "price_books"
    __table_args__ = (
        CheckConstraint(_in("plan_type", PLAN_TYPES), name="plan_type"),
        CheckConstraint(_in("unit_type", UNIT_TYPES), name="unit_type"),
        CheckConstraint("audience IN ('public','restricted')", name="audience"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name="code_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    plan_type: Mapped[str] = mapped_column(String(16))
    tier_label: Mapped[str | None] = mapped_column(Text)
    unit_type: Mapped[str] = mapped_column(String(8))
    audience: Mapped[str] = mapped_column(String(16), server_default=text("'public'"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    archived_at: Mapped[datetime | None]


class PriceBookVersion(Base):
    __tablename__ = "price_book_versions"
    __table_args__ = (
        UniqueConstraint("price_book_id", "version_no"),
        CheckConstraint(_in("status", VERSION_STATUSES), name="status"),
        CheckConstraint(_in("change_type", CHANGE_TYPES), name="change_type"),
        CheckConstraint(_in("tax_treatment", TAX_TREATMENTS), name="tax_treatment"),
        CheckConstraint("figures_confirmation IN ('supplied_unverified','confirmed')", name="figures_confirmation"),
        CheckConstraint("change_type <> 'correction' OR supersedes_version_id IS NOT NULL", name="correction_lineage"),
        CheckConstraint(
            "(figures_confirmation = 'confirmed') = (figures_confirmation_ref IS NOT NULL)", name="confirmation_ref"
        ),
        CheckConstraint("(tax_treatment = 'unknown') = (tax_treatment_ref IS NULL)", name="tax_ref"),
        CheckConstraint("session_minutes_per_unit BETWEEN 15 AND 240", name="minutes_per_unit"),
        CheckConstraint("version_no >= 1", name="version_no"),
        # The activation gate's hard parts, enforced by the database too (docs/04 §5.2).
        CheckConstraint(
            "status <> 'active' OR (figures_locked AND figures_confirmation = 'confirmed' "
            "AND tax_treatment <> 'unknown' AND unit_definition_ref IS NOT NULL AND approved_by IS NOT NULL "
            "AND content_hash IS NOT NULL AND activated_by IS NOT NULL)",
            name="active_requirements",
        ),
        CheckConstraint(
            "status NOT IN ('approved','active','superseded') OR approved_by IS NOT NULL", name="approval_recorded"
        ),
        CheckConstraint(
            "second_approved_by IS NULL OR (approved_by IS NOT NULL AND second_approved_by <> approved_by)",
            name="two_different_approvers",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from", name="dates"
        ),
        Index(
            "uq_price_book_versions_one_active",
            "price_book_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    price_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_books.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(16), server_default=text("'initial'"))
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_book_versions.id"))
    figures_locked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    figures_confirmation: Mapped[str] = mapped_column(String(24), server_default=text("'supplied_unverified'"))
    figures_confirmation_ref: Mapped[str | None] = mapped_column(Text)
    figures_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    figures_confirmed_at: Mapped[datetime | None]
    unit_definition_ref: Mapped[str | None] = mapped_column(Text)
    session_minutes_per_unit: Mapped[int] = mapped_column(SmallInteger, server_default=text("60"))
    tax_treatment: Mapped[str] = mapped_column(String(16), server_default=text("'unknown'"))
    tax_treatment_ref: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime | None]
    effective_to: Mapped[datetime | None]
    source_document: Mapped[str] = mapped_column(Text)
    source_received_on: Mapped[date] = mapped_column(Date)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    submitted_at: Mapped[datetime | None]
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None]
    second_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    second_approved_at: Mapped[datetime | None]
    activated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    activated_at: Mapped[datetime | None]
    content_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class PriceBookEntry(Base):
    __tablename__ = "price_book_entries"
    __table_args__ = (
        UniqueConstraint("price_book_version_id", "quantity"),
        UniqueConstraint("price_book_version_id", "package_code"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("package_total_minor > 0", name="package_total"),
        CheckConstraint("advertised_unit_rate_minor IS NULL OR advertised_unit_rate_minor > 0", name="advertised"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    price_book_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_book_versions.id"), index=True)
    package_code: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    package_total_minor: Mapped[int] = mapped_column(BigInteger)
    advertised_unit_rate_minor: Mapped[int | None] = mapped_column(BigInteger)
    # Information only ("effective rate"); never used to build a total (docs/04 §3.1).
    derived_unit_rate_minor: Mapped[int] = mapped_column(
        BigInteger, Computed("CAST(round(package_total_minor / quantity) AS bigint)", persisted=True)
    )
    is_purchasable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class PriceBookMarketAssignment(Base):
    __tablename__ = "price_book_market_assignments"
    __table_args__ = (
        UniqueConstraint("price_book_id", "market_id"),
        CheckConstraint("assignment_status IN ('unconfirmed','confirmed','revoked')", name="status"),
        CheckConstraint(
            "assignment_status <> 'confirmed' OR (decision_ref IS NOT NULL AND confirmed_by IS NOT NULL)",
            name="confirmation_complete",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    price_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_books.id"), index=True)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    assignment_status: Mapped[str] = mapped_column(String(16))
    is_market_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    decision_ref: Mapped[str | None] = mapped_column(Text)
    # Ireland: the relationship between its two schedules must be confirmed before either goes live (Q-PRC-03).
    requires_relationship_confirmation: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    relationship_confirmed_ref: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    confirmed_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)
    # Approved pricing rules (Phase 2b). None are confirmed today (Q-PRC-04, Q-PRC-10).
    eligibility_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_rules.id"))
    minimum_purchase_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_rules.id"))
    created_at: Mapped[datetime] = created_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class PricingTierSelection(Base):
    """A person's choice between valid tiers/schedules for one account (ADR-12). Never made by AI:
    ``selected_by_user_id`` references staff users only."""

    __tablename__ = "pricing_tier_selections"
    __table_args__ = (
        CheckConstraint("status IN ('active','replaced','revoked')", name="status"),
        CheckConstraint("length(btrim(reason)) >= 5", name="reason"),
        Index(
            "uq_pricing_tier_selections_one_active",
            "account_id",
            "opportunity_id",
            "market_id",
            "plan_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"))
    price_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_books.id"))
    plan_type: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    selected_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    selected_at: Mapped[datetime] = created_at_col()
    valid_until: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_tier_selections.id"))


class BenefitDefinition(Base):
    __tablename__ = "benefit_definitions"
    __table_args__ = (CheckConstraint("kind IN ('benefit','policy')", name="kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(8))
    supplied_scope: Mapped[str] = mapped_column(Text)  # as supplied, e.g. "Ireland packages"
    source_document: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class PackageBenefit(Base):
    """A benefit attached to one exact version (optionally one entry). Shown with a price only once approved
    (``benefits.claims_mode = approved_only``)."""

    __tablename__ = "package_benefits"
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved')", name="status"),
        CheckConstraint("(status = 'approved') = (approved_by IS NOT NULL)", name="approval"),
        CheckConstraint(
            "copied_from_id IS NULL OR cross_market_copy_approved_by IS NOT NULL", name="cross_market_copy"
        ),
        UniqueConstraint("price_book_version_id", "benefit_definition_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    price_book_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_book_versions.id"), index=True)
    price_book_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_book_entries.id"))
    benefit_definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benefit_definitions.id"))
    customer_facing_text: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None]
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("package_benefits.id"))
    cross_market_copy_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()


# ------------------------------------------------------------------------------ Phase 2b


class PricingImportBatch(Base):
    """A pricing sheet upload: validated first, applied as a new draft version only by a person."""

    __tablename__ = "pricing_import_batches"
    __table_args__ = (CheckConstraint("status IN ('validated','invalid','applied','discarded')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    filename: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    uploaded_at: Mapped[datetime] = created_at_col()
    status: Mapped[str] = mapped_column(String(16))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)  # per book: diff against the latest version, anomalies
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    applied_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    applied_at: Mapped[datetime | None]
    applied_version_ids: Mapped[list[str] | None] = mapped_column(JSONB)


class PricingImportRow(Base):
    __tablename__ = "pricing_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_no"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pricing_import_batches.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    errors: Mapped[list[str]] = mapped_column(JSONB)


class PricingRule(Base):
    """Eligibility or minimum-purchase logic as validated data (docs/04 §8, §11). Approved rules are immutable;
    a change is a new rule version."""

    __tablename__ = "pricing_rules"
    __table_args__ = (
        UniqueConstraint("code", "rule_version"),
        CheckConstraint("kind IN ('eligibility','minimum_purchase')", name="kind"),
        CheckConstraint("status IN ('draft','approved','retired')", name="status"),
        CheckConstraint("(status = 'draft') = (approved_by IS NULL)", name="approval"),
        CheckConstraint("approved_by IS NULL OR approved_by <> created_by", name="four_eyes"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name="code_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    decision_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]


class CustomerPricingAssignment(Base):
    """Special, confidential pricing for one customer: a restricted price book, requested and approved by two
    different people. Never created by AI."""

    __tablename__ = "customer_pricing_assignments"
    __table_args__ = (
        CheckConstraint("status IN ('pending_approval','active','rejected','revoked','expired')", name="status"),
        CheckConstraint("length(btrim(reason)) >= 5", name="reason"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="dates"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
        CheckConstraint("status <> 'active' OR approved_by IS NOT NULL", name="active_approved"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    price_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_books.id"))
    reason: Mapped[str] = mapped_column(Text)
    is_confidential: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    valid_from: Mapped[datetime]
    valid_to: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(24), server_default=text("'pending_approval'"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None]
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Promotion(Base):
    """A time-limited offer kept apart from standard pricing (BD-021, ADR-15): it never changes a price-book entry
    and is shown next to the list price, never folded into it."""

    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint("kind IN ('percent_off','amount_off','bonus_units')", name="kind"),
        CheckConstraint("status IN ('draft','in_review','approved','active','expired','cancelled')", name="status"),
        CheckConstraint("ends_at > starts_at", name="must_expire"),
        CheckConstraint("max_per_account >= 1", name="max_per_account"),
        CheckConstraint("max_redemptions IS NULL OR max_redemptions >= 1", name="max_redemptions"),
        CheckConstraint("approved_by IS NULL OR approved_by <> submitted_by", name="four_eyes"),
        CheckConstraint(
            "status NOT IN ('approved','active','expired') OR approved_by IS NOT NULL", name="approval_recorded"
        ),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{1,40}$'", name="code_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    eligibility_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_rules.id"))
    stackable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    max_per_account: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    decision_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None]
    activated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    activated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_col()


class PromotionTarget(Base):
    __tablename__ = "promotion_targets"
    __table_args__ = (
        CheckConstraint("price_book_version_id IS NOT NULL OR price_book_entry_id IS NOT NULL", name="has_target"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    promotion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("promotions.id"), index=True)
    price_book_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_book_versions.id"))
    price_book_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_book_entries.id"))
    market_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("markets.id"))
