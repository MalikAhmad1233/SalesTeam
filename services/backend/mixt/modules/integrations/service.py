"""Integration connections, encrypted credentials and the inbound webhook store (docs/07 §1).

- Secrets are encrypted with the field-encryption key ring, bound to their connection and kind,
  and never returned by any API: callers only learn which kinds are set and when they changed.
- A webhook is stored only after its signature has been verified, deduplicated by the provider's
  event id (or a hash of the body), and processed later by the worker so the provider gets a
  quick ``200``. Processing failures retry with backoff, then go to the dead-letter queue; a
  person can replay them once the cause is fixed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mixt.core import crypto
from mixt.core.context import SYSTEM_ACTOR, Actor
from mixt.core.errors import NotFound, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.events import service as events
from mixt.modules.identity.access import Access
from mixt.modules.integrations.models import (
    PROVIDERS,
    InboundWebhookEvent,
    IntegrationConnection,
    IntegrationCredential,
)

CREDENTIAL_KINDS = frozenset(
    {"access_token", "refresh_token", "app_secret", "verify_token", "client_secret", "api_key", "password"}
)
PROCESS_ACTION = "integrations.process_webhook"
MAX_SECRET_LENGTH = 4096

# Public names for other modules (they must not import integrations.models directly).
Connection = IntegrationConnection
WebhookEvent = InboundWebhookEvent

# provider -> processor(db, event) returning "processed" or "ignored"; raising means retry later.
WebhookProcessor = Callable[[Session, InboundWebhookEvent], str]
_PROCESSORS: dict[str, WebhookProcessor] = {}


def register_webhook_processor(provider: str, processor: WebhookProcessor) -> None:
    _PROCESSORS[provider] = processor


def register() -> None:
    events.register_action_handler(PROCESS_ACTION, _process_action, on_dead_letter=_process_gave_up)


# ------------------------------------------------------------------ connections and credentials


@dataclass(frozen=True)
class CredentialInfo:
    kind: str
    rotated_at: datetime


@dataclass(frozen=True)
class ConnectionView:
    connection: IntegrationConnection
    credentials: list[CredentialInfo]
    failed_webhooks: int


def _aad(connection_id: uuid.UUID, kind: str) -> str:
    return f"integration_credential:{connection_id}:{kind}"


def _check_secret(kind: str, value: str) -> str:
    if kind not in CREDENTIAL_KINDS:
        raise ValidationFailed("INVALID_CREDENTIAL_KIND", f"Unknown credential kind '{kind}'.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_SECRET_LENGTH:
        raise ValidationFailed("INVALID_CREDENTIAL", f"The {kind.replace('_', ' ')} is empty or too long.")
    return cleaned


def create_connection(
    db: Session,
    actor: Actor,
    access: Access,
    provider: str,
    display_name: str,
    config: dict[str, Any],
    secrets: dict[str, str],
) -> IntegrationConnection:
    access.require_somewhere("integrations.manage")
    if provider not in PROVIDERS:
        raise ValidationFailed("UNKNOWN_PROVIDER", f"Unknown provider '{provider}'.")
    if not display_name.strip():
        raise ValidationFailed("NAME_REQUIRED", "Give the connection a name.")
    cleaned = {kind: _check_secret(kind, value) for kind, value in secrets.items()}
    connection = IntegrationConnection(
        provider=provider,
        display_name=display_name.strip(),
        config=audit.jsonable(config),
        connected_by=actor.principal_id,
    )
    db.add(connection)
    db.flush()
    for kind, value in cleaned.items():
        _store_secret(db, connection.id, kind, value)
    audit.record(
        db,
        actor,
        "integration_connected",
        "integration_connection",
        connection.id,
        {"provider": provider, "display_name": connection.display_name, "credentials": sorted(cleaned)},
    )
    return connection


def _store_secret(db: Session, connection_id: uuid.UUID, kind: str, value: str) -> None:
    encrypted = crypto.encrypt_text(value, _aad(connection_id, kind))
    db.execute(
        insert(IntegrationCredential)
        .values(connection_id=connection_id, kind=kind, ciphertext=encrypted.ciphertext, key_id=encrypted.key_id)
        .on_conflict_do_update(
            index_elements=["connection_id", "kind"],
            set_={"ciphertext": encrypted.ciphertext, "key_id": encrypted.key_id, "rotated_at": func.now()},
        )
    )


def set_credential(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID, kind: str, value: str) -> None:
    """Add or rotate a secret. The old value is overwritten; the audit log records that it changed."""
    access.require_somewhere("integrations.manage")
    connection = get_connection(db, connection_id)
    _store_secret(db, connection.id, kind, _check_secret(kind, value))
    audit.record(db, actor, "integration_credential_rotated", "integration_connection", connection.id, {"kind": kind})


def secret(db: Session, connection_id: uuid.UUID, kind: str) -> str | None:
    """Decrypted secret for internal use by an adapter. Never return it to a caller or log it."""
    row = db.execute(  # columns, not the entity: a rotation in this transaction must be seen
        select(IntegrationCredential.ciphertext, IntegrationCredential.key_id).where(
            IntegrationCredential.connection_id == connection_id, IntegrationCredential.kind == kind
        )
    ).first()
    if row is None:
        return None
    return crypto.decrypt_text(crypto.EncryptedValue(row.ciphertext, row.key_id), _aad(connection_id, kind))


def get_connection(db: Session, connection_id: uuid.UUID) -> IntegrationConnection:
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Integration connection not found.")
    return connection


def _view(db: Session, connection: IntegrationConnection) -> ConnectionView:
    creds = db.execute(
        select(IntegrationCredential.kind, IntegrationCredential.rotated_at)
        .where(IntegrationCredential.connection_id == connection.id)
        .order_by(IntegrationCredential.kind)
    ).all()
    failed = db.scalar(
        select(func.count())
        .select_from(InboundWebhookEvent)
        .where(InboundWebhookEvent.connection_id == connection.id, InboundWebhookEvent.status == "failed")
    )
    return ConnectionView(connection, [CredentialInfo(k, r) for k, r in creds], int(failed or 0))


def view_connection(db: Session, access: Access, connection_id: uuid.UUID) -> ConnectionView:
    access.require_somewhere("integrations.manage")
    return _view(db, get_connection(db, connection_id))


def list_connections(db: Session, access: Access) -> list[ConnectionView]:
    access.require_somewhere("integrations.manage")
    rows = db.scalars(select(IntegrationConnection).order_by(IntegrationConnection.connected_at))
    return [_view(db, c) for c in rows]


def connections_for(db: Session, provider: str) -> list[IntegrationConnection]:
    return list(
        db.scalars(
            select(IntegrationConnection)
            .where(IntegrationConnection.provider == provider, IntegrationConnection.status != "disconnected")
            .order_by(IntegrationConnection.connected_at)
        )
    )


def update_config(
    db: Session, actor: Actor, access: Access, connection_id: uuid.UUID, changes: dict[str, Any]
) -> IntegrationConnection:
    access.require_somewhere("integrations.manage")
    connection = get_connection(db, connection_id)
    before = dict(connection.config)
    connection.config = audit.jsonable({**before, **changes})
    db.flush()
    audit.record(
        db,
        actor,
        "integration_config_changed",
        "integration_connection",
        connection.id,
        audit.diff(before, connection.config),
    )
    return connection


def disconnect(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID) -> IntegrationConnection:
    """Stop using a connection. Its secrets are destroyed; its history stays."""
    access.require_somewhere("integrations.manage")
    connection = get_connection(db, connection_id)
    if connection.status == "disconnected":
        return connection
    connection.status = "disconnected"
    db.query(IntegrationCredential).filter(IntegrationCredential.connection_id == connection.id).delete()
    db.flush()
    audit.record(db, actor, "integration_disconnected", "integration_connection", connection.id, {})
    return connection


def mark_success(db: Session, connection: IntegrationConnection) -> None:
    if connection.status == "disconnected":
        return
    connection.status, connection.last_success_at, connection.last_error = "connected", now_utc(), None
    db.flush()


def mark_error(db: Session, connection: IntegrationConnection, error: str) -> None:
    if connection.status == "disconnected":
        return
    if connection.status != "error":
        audit.record(
            db, SYSTEM_ACTOR, "integration_error", "integration_connection", connection.id, {"error": error[:500]}
        )
    connection.status, connection.last_error = "error", error[:2000]
    db.flush()


def record_rejected_webhook(db: Session, connection_id: uuid.UUID) -> None:
    """Count a webhook that failed verification (it is not stored)."""
    db.execute(
        update(IntegrationConnection)
        .where(IntegrationConnection.id == connection_id)
        .values(rejected_webhooks=IntegrationConnection.rejected_webhooks + 1, last_rejected_at=func.now())
    )


# ------------------------------------------------------------------ webhooks


@dataclass(frozen=True)
class StoredWebhook:
    event: InboundWebhookEvent
    action_id: uuid.UUID  # the processing job, which can be run straight away


def store_webhook(
    db: Session, connection: IntegrationConnection, external_event_id: str, payload: dict[str, Any]
) -> StoredWebhook | None:
    """Store a verified webhook and queue it for processing. None when it was already received."""
    event_id = db.scalar(
        insert(InboundWebhookEvent)
        .values(
            connection_id=connection.id,
            provider=connection.provider,
            external_event_id=external_event_id,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["provider", "external_event_id"])
        .returning(InboundWebhookEvent.id)
    )
    event = db.get(InboundWebhookEvent, event_id) if event_id is not None else None
    if event is None:
        return None
    action = events.schedule(
        db, SYSTEM_ACTOR, PROCESS_ACTION, {"event_id": event.id}, now_utc(), dedupe_key=_key(event.id)
    )
    return StoredWebhook(event, action.id)


def _key(event_id: uuid.UUID) -> str:
    return f"webhook:{event_id}"


def _process_action(db: Session, action: events.Action) -> None:
    event = db.get(InboundWebhookEvent, uuid.UUID(str(action.payload["event_id"])))
    if event is None or event.status in ("processed", "ignored"):
        return
    processor = _PROCESSORS.get(event.provider)
    if processor is None:
        raise LookupError(f"no webhook processor for '{event.provider}'")
    outcome = processor(db, event)
    event.status = outcome if outcome in ("processed", "ignored") else "processed"
    event.attempts += 1
    event.processed_at = now_utc()
    event.last_error = None
    db.flush()


def _process_gave_up(db: Session, action: events.Action) -> None:
    event = db.get(InboundWebhookEvent, uuid.UUID(str(action.payload["event_id"])))
    if event is not None:
        event.status, event.attempts, event.last_error = "failed", action.attempts, action.last_error
        db.flush()


def list_webhook_events(
    db: Session, access: Access, connection_id: uuid.UUID, status: str | None = None, limit: int = 50
) -> list[InboundWebhookEvent]:
    access.require_somewhere("integrations.manage")
    get_connection(db, connection_id)
    query = select(InboundWebhookEvent).where(InboundWebhookEvent.connection_id == connection_id)
    if status is not None:
        query = query.where(InboundWebhookEvent.status == status)
    return list(db.scalars(query.order_by(InboundWebhookEvent.received_at.desc()).limit(min(limit, 200))))


def replay_webhook(db: Session, actor: Actor, access: Access, event_id: uuid.UUID) -> InboundWebhookEvent:
    """Process a failed webhook again (after the cause has been fixed)."""
    access.require_somewhere("integrations.manage")
    event = db.get(InboundWebhookEvent, event_id)
    if event is None:
        raise NotFound("WEBHOOK_NOT_FOUND", "Webhook event not found.")
    if event.status != "failed":
        raise ValidationFailed("WEBHOOK_NOT_FAILED", "Only failed webhooks can be replayed.")
    if not events.replay_action(db, actor, _key(event.id)):
        events.schedule(db, actor, PROCESS_ACTION, {"event_id": event.id}, now_utc(), dedupe_key=_key(event.id))
    event.status, event.last_error = "received", None
    db.flush()
    audit.record(db, actor, "webhook_replayed", "inbound_webhook_event", event.id, {"provider": event.provider})
    return event
