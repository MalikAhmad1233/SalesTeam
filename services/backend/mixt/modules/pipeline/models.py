"""Opportunities and their stage history. Stages are configuration (setting ``crm.pipeline_stages``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint("pipeline IN ('new_business')", name="pipeline"),
        CheckConstraint("kind IN ('new_business','sibling_addition','win_back')", name="kind"),
        CheckConstraint("(budget_amount_minor IS NULL) = (budget_currency IS NULL)", name="budget_has_currency"),
        CheckConstraint("budget_amount_minor IS NULL OR budget_amount_minor >= 0", name="budget_not_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    pipeline: Mapped[str] = mapped_column(String(32), server_default=text("'new_business'"))
    stage_key: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), server_default=text("'new_business'"))
    title: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    budget_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_currency: Mapped[str | None] = mapped_column(ForeignKey("currencies.code"))
    budget_notes: Mapped[str | None] = mapped_column(Text)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    lost_reason_code: Mapped[str | None] = mapped_column(Text)
    lost_notes: Mapped[str | None] = mapped_column(Text)
    nurture_until: Mapped[date | None] = mapped_column(Date)
    source_lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id"))
    stage_entered_at: Mapped[datetime] = created_at_col()
    opened_at: Mapped[datetime] = created_at_col()
    closed_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class OpportunityStudent(Base):
    __tablename__ = "opportunity_students"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), primary_key=True)


class OpportunityStageHistory(Base):
    __tablename__ = "opportunity_stage_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[str | None] = mapped_column(Text)
    to_stage: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    changed_at: Mapped[datetime] = created_at_col()


Index("ix_opportunities_stage_owner", Opportunity.stage_key, Opportunity.owner_user_id)
