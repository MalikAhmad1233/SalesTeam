"""Transactional outbox, consumer bookkeeping, scheduled actions and dead letters (docs/01 §6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, uuid_pk


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(Text)
    aggregate_type: Mapped[str] = mapped_column(Text)
    aggregate_id: Mapped[str] = mapped_column(Text)
    account_id: Mapped[uuid.UUID | None]  # lets the timeline place the event without decoding the payload
    payload: Mapped[dict[str, Any]]
    actor_principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    occurred_at: Mapped[datetime] = created_at_col()
    dispatched_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)


class EventConsumption(Base):
    """Records that a consumer handled an event, so redelivery never repeats the work."""

    __tablename__ = "event_consumptions"

    consumer: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id", ondelete="CASCADE"), primary_key=True)
    processed_at: Mapped[datetime] = created_at_col()


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"
    __table_args__ = (CheckConstraint("status IN ('pending','done','cancelled','failed')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    action_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]]
    due_at: Mapped[datetime]
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None]


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (CheckConstraint("source IN ('outbox','scheduled_action')", name="source"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(24))
    ref_id: Mapped[uuid.UUID]
    handler: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    failed_at: Mapped[datetime] = created_at_col()
    replayed_at: Mapped[datetime | None]
    replayed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))


Index("ix_outbox_pending", OutboxEvent.occurred_at, postgresql_where=text("dispatched_at IS NULL"))
Index("ix_outbox_account", OutboxEvent.account_id, OutboxEvent.occurred_at)
Index("ix_scheduled_actions_due", ScheduledAction.due_at, postgresql_where=text("status = 'pending'"))
