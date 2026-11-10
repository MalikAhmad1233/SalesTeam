"""Lead sources, campaigns, leads, spreadsheet imports, duplicate candidates and merge records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, uuid_pk


class LeadSource(Base):
    __tablename__ = "lead_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    manual_entry_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("lead_source_id", "name"),
        CheckConstraint("status IN ('active','ended')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    lead_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_sources.id"))
    name: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[dict[str, Any] | None]
    market_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("markets.id"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()


class LeadImportBatch(Base):
    __tablename__ = "lead_import_batches"
    __table_args__ = (CheckConstraint("status IN ('validated','imported','discarded')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    file_name: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    row_count: Mapped[int] = mapped_column(Integer)
    valid_count: Mapped[int] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(Integer)
    imported_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    default_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    report: Mapped[dict[str, Any]]  # per-row results; personal data is removed once imported or discarded
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    finished_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    finished_at: Mapped[datetime | None]


class Lead(Base):
    """The raw, unaltered record of one enquiry, kept for attribution after it is matched to a household."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("lead_source_id", "external_id"),
        CheckConstraint("status IN ('new_account','matched','out_of_market','spam','rejected')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    lead_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_sources.id"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_import_batches.id"))
    external_id: Mapped[str | None] = mapped_column(Text)
    submitted_name: Mapped[str | None] = mapped_column(Text)
    submitted_email: Mapped[str | None] = mapped_column(CITEXT)
    submitted_phone: Mapped[str | None] = mapped_column(Text)
    submitted_country: Mapped[str | None] = mapped_column(String(2))
    submitted_message: Mapped[str | None] = mapped_column(Text)
    submitted_fields: Mapped[dict[str, Any]]
    utm: Mapped[dict[str, Any] | None]
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    status: Mapped[str] = mapped_column(String(16))
    status_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    reviewed_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    received_at: Mapped[datetime] = created_at_col()


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("account_id", "candidate_account_id"),
        CheckConstraint("status IN ('open','merged','dismissed')", name="status"),
        CheckConstraint("account_id <> candidate_account_id", name="distinct_accounts"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    candidate_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Numeric(4, 3, asdecimal=False))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'open'"))
    created_at: Mapped[datetime] = created_at_col()
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    resolved_at: Mapped[datetime | None]


class RecordMerge(Base):
    __tablename__ = "record_merges"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(Text)
    surviving_id: Mapped[uuid.UUID]
    merged_id: Mapped[uuid.UUID]
    snapshot: Mapped[dict[str, Any]]
    merged_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    merged_at: Mapped[datetime] = created_at_col()
