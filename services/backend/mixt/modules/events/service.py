"""Domain events and scheduled actions.

- ``emit`` writes an outbox row in the caller's transaction, so an event exists if and only if
  the change that caused it was committed.
- ``dispatch_outbox`` delivers pending events to registered consumers. Each consumer runs in its
  own savepoint and is recorded in ``event_consumptions``, so retries never repeat finished work.
  After ``MAX_ATTEMPTS`` failures an event goes to the dead-letter table for a person to replay.
- ``schedule`` stores business-timed work in PostgreSQL; ``run_due_actions`` claims due rows with
  ``FOR UPDATE SKIP LOCKED`` so several workers can run safely.
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import NotFound, ValidationFailed
from mixt.core.logging import get_logger
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.events.models import DeadLetter, EventConsumption, OutboxEvent, ScheduledAction

# Public names for consumers in other modules (they must not import events.models directly).
Event = OutboxEvent
Action = ScheduledAction

MAX_ATTEMPTS = 5
log = get_logger("mixt.events")

EventHandler = Callable[[Session, OutboxEvent], None]
ActionHandler = Callable[[Session, ScheduledAction], None]


@dataclass(frozen=True)
class Consumer:
    name: str
    event_types: frozenset[str]  # empty = all events
    handler: EventHandler


_CONSUMERS: dict[str, Consumer] = {}
_ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_consumer(name: str, event_types: set[str] | None, handler: EventHandler) -> None:
    _CONSUMERS[name] = Consumer(name, frozenset(event_types or ()), handler)


def register_action_handler(action_type: str, handler: ActionHandler) -> None:
    _ACTION_HANDLERS[action_type] = handler


def consumers() -> list[Consumer]:
    return list(_CONSUMERS.values())


def action_types() -> list[str]:
    return sorted(_ACTION_HANDLERS)


def emit(
    db: Session,
    actor: Actor,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID | str,
    payload: dict[str, Any],
    account_id: uuid.UUID | None = None,
) -> OutboxEvent:
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        account_id=account_id,
        payload=audit.jsonable(payload),
        actor_principal_id=actor.principal_id,
    )
    db.add(event)
    db.flush()
    return event


def _subscribed(consumer: Consumer, event: OutboxEvent) -> bool:
    return not consumer.event_types or event.event_type in consumer.event_types


@dataclass
class DispatchResult:
    delivered: int = 0
    failed: int = 0
    dead_lettered: int = 0


def dispatch_outbox(db: Session, limit: int = 100) -> DispatchResult:
    """Deliver pending events, oldest first. Safe to run concurrently (rows are locked)."""
    result = DispatchResult()
    events = list(
        db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None))
            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for event in events:
        done = set(db.scalars(select(EventConsumption.consumer).where(EventConsumption.event_id == event.id)))
        errors: list[str] = []
        for consumer in _CONSUMERS.values():
            if consumer.name in done or not _subscribed(consumer, event):
                continue
            try:
                with db.begin_nested():
                    consumer.handler(db, event)
                    db.add(EventConsumption(consumer=consumer.name, event_id=event.id))
                    db.flush()
            except Exception as exc:  # a consumer failure must not block other events
                errors.append(f"{consumer.name}: {exc}")
                log.warning("event_consumer_failed", consumer=consumer.name, event_type=event.event_type)
        if errors:
            event.attempts += 1
            event.last_error = "; ".join(errors)[:2000]
            result.failed += 1
            if event.attempts >= MAX_ATTEMPTS:
                event.dispatched_at = now_utc()
                db.add(DeadLetter(source="outbox", ref_id=event.id, handler="consumers", error=event.last_error))
                result.dead_lettered += 1
        else:
            event.dispatched_at = now_utc()
            result.delivered += 1
    db.flush()
    return result


def schedule(
    db: Session,
    actor: Actor,
    action_type: str,
    payload: dict[str, Any],
    due_at: datetime,
    dedupe_key: str | None = None,
) -> ScheduledAction:
    """Store work to run at ``due_at``. A pending action with the same ``dedupe_key`` is replaced."""
    if due_at.tzinfo is None:
        raise ValidationFailed("NAIVE_DATETIME", "Scheduled times must include a time zone.")
    if dedupe_key is not None:
        existing = db.scalar(select(ScheduledAction).where(ScheduledAction.dedupe_key == dedupe_key))
        if existing is not None:
            if existing.status == "pending":
                existing.payload = audit.jsonable(payload)
                existing.due_at = due_at
                db.flush()
                return existing
            existing.dedupe_key = None  # keep history of the finished one, free the key
            db.flush()
    action = ScheduledAction(
        action_type=action_type,
        payload=audit.jsonable(payload),
        due_at=due_at,
        dedupe_key=dedupe_key,
        created_by=actor.principal_id,
    )
    db.add(action)
    db.flush()
    return action


def cancel(db: Session, dedupe_key: str) -> bool:
    result = db.execute(
        update(ScheduledAction)
        .where(ScheduledAction.dedupe_key == dedupe_key, ScheduledAction.status == "pending")
        .values(status="cancelled", completed_at=now_utc())
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


@dataclass
class ActionRunResult:
    done: int = 0
    failed: int = 0
    dead_lettered: int = 0


def run_due_actions(db: Session, now: datetime | None = None, limit: int = 100) -> ActionRunResult:
    now = now or now_utc()
    result = ActionRunResult()
    actions = list(
        db.scalars(
            select(ScheduledAction)
            .where(ScheduledAction.status == "pending", ScheduledAction.due_at <= now)
            .order_by(ScheduledAction.due_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for action in actions:
        handler = _ACTION_HANDLERS.get(action.action_type)
        try:
            if handler is None:
                raise LookupError(f"no handler registered for '{action.action_type}'")
            with db.begin_nested():
                handler(db, action)
            action.status = "done"
            action.completed_at = now_utc()
            result.done += 1
        except Exception as exc:
            action.attempts += 1
            action.last_error = "".join(traceback.format_exception_only(exc)).strip()[:2000]
            result.failed += 1
            if action.attempts >= MAX_ATTEMPTS or handler is None:
                action.status = "failed"
                action.completed_at = now_utc()
                db.add(
                    DeadLetter(
                        source="scheduled_action", ref_id=action.id, handler=action.action_type, error=action.last_error
                    )
                )
                result.dead_lettered += 1
    db.flush()
    return result


def list_dead_letters(db: Session, include_replayed: bool = False) -> list[DeadLetter]:
    query = select(DeadLetter).order_by(DeadLetter.failed_at.desc())
    if not include_replayed:
        query = query.where(DeadLetter.replayed_at.is_(None))
    return list(db.scalars(query))


def replay_dead_letter(db: Session, actor: Actor, dead_letter_id: uuid.UUID) -> None:
    """Put the failed event or action back in the queue (after the cause has been fixed)."""
    letter = db.get(DeadLetter, dead_letter_id)
    if letter is None or letter.replayed_at is not None:
        raise NotFound("DEAD_LETTER_NOT_FOUND", "Dead letter not found or already replayed.")
    if letter.source == "outbox":
        event = db.get(OutboxEvent, letter.ref_id)
        if event is not None:
            event.dispatched_at, event.attempts = None, 0
    else:
        action = db.get(ScheduledAction, letter.ref_id)
        if action is not None:
            action.status, action.attempts, action.completed_at = "pending", 0, None
    letter.replayed_at = now_utc()
    letter.replayed_by = actor.principal_id
    audit.record(db, actor, "dead_letter_replayed", "dead_letter", letter.id, {"source": letter.source})
