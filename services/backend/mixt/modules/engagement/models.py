"""Tasks, notes, tags and the customer timeline (activities)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "type IN ('follow_up','call','review','data_fix','payment_chase','renewal','other')", name="type"
        ),
        CheckConstraint("status IN ('open','in_progress','snoozed','done','cancelled')", name="status"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority"),
        CheckConstraint("source IN ('manual','system')", name="source"),
        CheckConstraint("status <> 'snoozed' OR snoozed_until IS NOT NULL", name="snooze_has_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    type: Mapped[str] = mapped_column(String(24), server_default=text("'follow_up'"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None]
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("2"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'open'"))
    snoozed_until: Mapped[datetime | None]
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), server_default=text("'manual'"))
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    completed_at: Mapped[datetime | None]
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}


class Note(Base):
    """Notes are immutable once written (corrections are new notes), so the record stays trustworthy."""

    __tablename__ = "notes"
    __table_args__ = (CheckConstraint("visibility IN ('team','private')", name="visibility"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), server_default=text("'team'"))
    author_principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(CITEXT, unique=True)
    color: Mapped[str | None] = mapped_column(String(7))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()


class AccountTag(Base):
    __tablename__ = "account_tags"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    tagged_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    tagged_at: Mapped[datetime] = created_at_col()


class Activity(Base):
    """Customer timeline entry, built from domain events by the timeline consumer."""

    __tablename__ = "activities"
    __table_args__ = (CheckConstraint("visibility IN ('team','private')", name="visibility"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outbox_events.id"), unique=True)
    type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), server_default=text("'team'"))
    actor_principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    details: Mapped[dict[str, Any] | None]
    occurred_at: Mapped[datetime]


Index("ix_activities_account_time", Activity.account_id, Activity.occurred_at.desc())
Index(
    "ix_tasks_assignee_open",
    Task.assignee_user_id,
    Task.due_at,
    postgresql_where=text("status IN ('open','in_progress','snoozed')"),
)
