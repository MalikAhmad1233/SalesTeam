"""Quotation tables (docs/02 §9). Private to the quotations module.

Database guards (migration 0006): lines can only change while their quotation is a draft; once a
quotation is approved its snapshot, hash, totals, currency, market and validity never change, and
quotations are never deleted (they are cancelled or superseded).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
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

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk

STATUSES = (
    "draft",
    "pending_approval",
    "approved",
    "issued",
    "accepted",
    "declined",
    "expired",
    "superseded",
    "cancelled",
)


class Quotation(Base):
    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("quote_number", "revision_no"),
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in STATUSES)})", name="status"),
        CheckConstraint("revision_no >= 1", name="revision_no"),
        CheckConstraint("total_minor = subtotal_minor - promotion_total_minor - discount_total_minor", name="totals"),
        CheckConstraint("discount_total_minor >= 0 AND promotion_total_minor >= 0", name="non_negative"),
        CheckConstraint(
            "status IN ('draft','pending_approval','cancelled') "
            "OR (snapshot_hash IS NOT NULL AND valid_until IS NOT NULL)",
            name="approved_has_snapshot",
        ),
        CheckConstraint(
            "status NOT IN ('issued','accepted','declined') "
            "OR (issued_at IS NOT NULL AND issued_to_contact_id IS NOT NULL)",
            name="issued_complete",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    quote_number: Mapped[str] = mapped_column(Text)
    revision_no: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    parent_quotation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotations.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("markets.id"))
    currency_code: Mapped[str | None] = mapped_column(ForeignKey("currencies.code"))
    status: Mapped[str] = mapped_column(String(24), server_default=text("'draft'"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    promotion_total_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    discount_total_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    total_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    tax_treatment: Mapped[str | None] = mapped_column(String(16))
    discount_reason: Mapped[str | None] = mapped_column(Text)
    required_approvals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pricing_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    snapshot_hash: Mapped[str | None] = mapped_column(Text)
    prepared_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    submitted_at: Mapped[datetime | None]
    approved_at: Mapped[datetime | None]
    issued_at: Mapped[datetime | None]
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    issued_to_contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    issued_via: Mapped[str | None] = mapped_column(String(24))
    outcome_at: Mapped[datetime | None]
    outcome_recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    outcome_note: Mapped[str | None] = mapped_column(Text)
    customer_note: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class QuotationLine(Base):
    __tablename__ = "quotation_lines"
    __table_args__ = (
        UniqueConstraint("quotation_id", "line_no"),
        CheckConstraint(
            "final_total_minor = list_total_minor - promotion_discount_minor - discount_minor", name="final_total"
        ),
        CheckConstraint("discount_minor >= 0 AND promotion_discount_minor >= 0", name="non_negative"),
        CheckConstraint("final_total_minor > 0", name="positive_total"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id"), index=True)
    line_no: Mapped[int] = mapped_column(SmallInteger)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("students.id"))
    price_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_books.id"))
    price_book_code: Mapped[str] = mapped_column(Text)
    price_book_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_book_versions.id"))
    price_book_version_no: Mapped[int] = mapped_column(Integer)
    price_book_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_book_entries.id"))
    package_code: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    plan_type: Mapped[str] = mapped_column(String(16))
    tier_label: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    unit_type: Mapped[str] = mapped_column(String(8))
    session_minutes_per_unit: Mapped[int] = mapped_column(SmallInteger)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    list_total_minor: Mapped[int] = mapped_column(BigInteger)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("promotions.id"))
    promotion_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    promotion_discount_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    bonus_units: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    discount_minor: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    final_total_minor: Mapped[int] = mapped_column(BigInteger)
    special_assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_pricing_assignments.id"))
    tier_selection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_tier_selections.id"))
    benefits_snapshot: Mapped[list[str]] = mapped_column(JSONB)


class QuotationApproval(Base):
    """One person's approval of one quotation. The role it counts for is recorded with it."""

    __tablename__ = "quotation_approvals"
    __table_args__ = (
        UniqueConstraint("quotation_id", "decided_by_user_id"),
        CheckConstraint("decision IN ('approve','reject')", name="decision"),
        CheckConstraint("capacity IN ('sales','pricing')", name="capacity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id"), index=True)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    capacity: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = created_at_col()


class PromotionRedemption(Base):
    __tablename__ = "promotion_redemptions"
    __table_args__ = (UniqueConstraint("promotion_id", "quotation_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    promotion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("promotions.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id"))
    redeemed_at: Mapped[datetime] = created_at_col()
