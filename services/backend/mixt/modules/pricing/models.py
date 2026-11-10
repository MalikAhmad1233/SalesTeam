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
