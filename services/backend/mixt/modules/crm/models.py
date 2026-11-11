"""CRM tables: households (accounts), contacts, contact points, consents, students.

Key rules encoded here:
- ``market_id`` is the confirmed *pricing* market; it is only set by a person (ADR-13) and is never
  inferred from currency, phone prefix or curriculum.
- consents are append-only (trigger), so the consent history can't be rewritten.
- students store year of birth only (setting ``crm.student_birth_data = year_only``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Sequence,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk

ACCOUNT_NUMBER_SEQ = Sequence("account_number_seq", start=1)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("kind IN ('household','institution')", name="kind"),
        CheckConstraint(
            "lifecycle_stage IN ('lead','prospect','customer','former_customer','disqualified','out_of_market')",
            name="lifecycle_stage",
        ),
        CheckConstraint("status IN ('active','archived','anonymised')", name="status"),
        CheckConstraint(
            "(market_id IS NULL) = (market_confirmed_by IS NULL AND market_confirmed_at IS NULL)",
            name="market_confirmation_complete",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_number: Mapped[str] = mapped_column(
        Text,
        unique=True,
        server_default=text("'MX-' || lpad(nextval('account_number_seq')::text, 6, '0')"),
    )
    kind: Mapped[str] = mapped_column(String(16), server_default=text("'household'"))
    display_name: Mapped[str] = mapped_column(Text)
    country_of_residence: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    market_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("markets.id"), index=True)
    market_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    market_confirmed_at: Mapped[datetime | None]
    market_confirmation_note: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str | None] = mapped_column(ForeignKey("languages.code"))
    lifecycle_stage: Mapped[str] = mapped_column(String(24), server_default=text("'lead'"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_vip: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    first_touch_lead_source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_sources.id"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (CheckConstraint("role IN ('guardian','payer','student','other')", name="role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    preferred_name: Mapped[str | None] = mapped_column(Text)
    relationship_to_students: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_decision_maker: Mapped[bool | None] = mapped_column(Boolean)
    preferred_language: Mapped[str | None] = mapped_column(ForeignKey("languages.code"))
    timezone: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class ContactPoint(Base):
    __tablename__ = "contact_points"
    __table_args__ = (
        CheckConstraint("kind IN ('phone','whatsapp','email','instagram','web_chat')", name="kind"),
        CheckConstraint("status IN ('active','bounced','invalid','opted_out')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text)  # normalised: E.164 / lower-case email / scoped id
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    verified_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Consent(Base):
    """Append-only consent history; the current state is the latest row per contact/point/purpose."""

    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('service_messages','marketing_whatsapp','marketing_email','session_recording',"
            "'ai_assisted_conversation','data_processing')",
            name="purpose",
        ),
        CheckConstraint("status IN ('granted','withdrawn','denied')", name="status"),
        CheckConstraint(
            "legal_basis IN ('consent','contract','legitimate_interests','legal_obligation')", name="legal_basis"
        ),
        CheckConstraint(
            "source IN ('web_form','lead_ad_form','whatsapp_keyword','email_reply','email_link','staff_logged',"
            "'import')",
            name="source",
        ),
        CheckConstraint("jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb", name="evidence_present"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id"), index=True)
    contact_point_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contact_points.id"))
    purpose: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    legal_basis: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(24))
    evidence: Mapped[dict[str, Any]]
    captured_at: Mapped[datetime] = created_at_col()
    captured_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("status IN ('prospective','active','paused','alumni')", name="status"),
        CheckConstraint("birth_year IS NULL OR birth_year BETWEEN 1950 AND 2100", name="birth_year_range"),
        CheckConstraint(
            "(learning_needs_ciphertext IS NULL) = (learning_needs_key_id IS NULL)", name="learning_needs_pair"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    preferred_name: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("curricula.id"))
    grade_level_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grade_levels.id"))
    grade_text: Mapped[str | None] = mapped_column(Text)  # free text until grade lists exist (Q-ACA-03)
    school_name: Mapped[str | None] = mapped_column(Text)
    country_of_study: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    timezone: Mapped[str | None] = mapped_column(Text)
    goals: Mapped[str | None] = mapped_column(Text)
    learning_needs_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    learning_needs_key_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'prospective'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class StudentSubject(Base):
    __tablename__ = "student_subjects"
    __table_args__ = (CheckConstraint("status IN ('interested','active','completed','dropped')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subjects.id"))
    subject_name: Mapped[str] = mapped_column(Text)  # free text until a subject list exists (Q-ACA-01)
    exam_board_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exam_boards.id"))
    qualification_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("qualifications.id"))
    current_grade: Mapped[str | None] = mapped_column(Text)
    target_grade: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'interested'"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class StudentExam(Base):
    __tablename__ = "student_exams"
    __table_args__ = (CheckConstraint("source IN ('customer','staff','ai_extracted')", name="source"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    student_subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("student_subjects.id", ondelete="SET NULL"))
    exam_board_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exam_boards.id"))
    qualification_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("qualifications.id"))
    exam_session: Mapped[str | None] = mapped_column(Text)
    exam_date: Mapped[date | None] = mapped_column(Date)
    paper_code: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))
    is_confirmed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class SchedulingPreference(Base):
    __tablename__ = "scheduling_preferences"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), unique=True)
    timezone: Mapped[str] = mapped_column(Text)
    preferred_weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    preferred_windows: Mapped[dict[str, Any] | None]
    lessons_per_week: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    preferred_session_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = updated_at_col()


Index(
    "uq_contacts_one_primary_per_account",
    Contact.account_id,
    unique=True,
    postgresql_where=text("is_primary AND archived_at IS NULL"),
)
Index("ix_contact_points_kind_value", ContactPoint.kind, ContactPoint.value)
Index(
    "ix_accounts_display_name_trgm",
    Account.display_name,
    postgresql_using="gin",
    postgresql_ops={"display_name": "gin_trgm_ops"},
)
Index("ix_consents_current", Consent.contact_id, Consent.purpose, Consent.captured_at)
