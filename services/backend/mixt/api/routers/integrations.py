"""Integrations API (Phase 3a): connections, WhatsApp setup, templates, webhook failures, suppression list.

Secrets go in and never come out: responses only say which credential kinds are set and when.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, require
from mixt.core.config import get_config
from mixt.core.db import get_session
from mixt.modules.crm import service as crm
from mixt.modules.integrations import service as integrations
from mixt.modules.messaging import channels
from mixt.modules.messaging import service as messaging

router = APIRouter(tags=["integrations"])


class CredentialOut(BaseModel):
    kind: str
    rotated_at: datetime


class ChannelAccountOut(BaseModel):
    id: uuid.UUID
    channel: str
    display_name: str
    address: str | None
    status: str
    enabled: bool
    last_checked_at: str | None = None
    last_check_error: str | None = None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    display_name: str
    status: str
    config: dict[str, Any]
    connected_at: datetime
    last_success_at: datetime | None
    last_error: str | None
    rejected_webhooks: int
    last_rejected_at: datetime | None
    failed_webhooks: int
    credentials: list[CredentialOut]
    webhook_path: str | None
    webhook_url: str | None
    channel_account: ChannelAccountOut | None


def _channel_out(db: Session, account: Any | None) -> ChannelAccountOut | None:
    if account is None:
        return None
    return ChannelAccountOut(
        id=account.id,
        channel=account.channel,
        display_name=account.display_name,
        address=account.address,
        status=account.status,
        enabled=channels.is_enabled(db, account),
        last_checked_at=(account.sync_state or {}).get("last_polled_at"),
        last_check_error=(account.sync_state or {}).get("last_error"),
    )


def _out(db: Session, view: integrations.ConnectionView) -> ConnectionOut:
    c = view.connection
    path = f"/webhooks/whatsapp/{c.id}" if c.provider == channels.WHATSAPP else None
    base = get_config().public_base_url
    return ConnectionOut(
        id=c.id,
        provider=c.provider,
        display_name=c.display_name,
        status=c.status,
        config=c.config,
        connected_at=c.connected_at,
        last_success_at=c.last_success_at,
        last_error=c.last_error,
        rejected_webhooks=c.rejected_webhooks,
        last_rejected_at=c.last_rejected_at,
        failed_webhooks=view.failed_webhooks,
        credentials=[CredentialOut(kind=k.kind, rotated_at=k.rotated_at) for k in view.credentials],
        webhook_path=path,
        webhook_url=f"{base.rstrip('/')}{path}" if base and path else None,
        channel_account=_channel_out(db, channels.channel_account_for(db, c.id)),
    )


@router.get("/integrations", response_model=list[ConnectionOut])
def list_connections(
    auth: AuthContext = Depends(require("integrations.manage")), db: Session = Depends(get_session)
) -> list[ConnectionOut]:
    return [_out(db, v) for v in integrations.list_connections(db, auth.access)]


class WhatsAppIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    graph_api_version: str = Field(min_length=2, max_length=10, description="e.g. v21.0, as set on Meta's app")
    waba_id: str = Field(min_length=5, max_length=32)
    phone_number_id: str = Field(min_length=5, max_length=32)
    display_phone_number: str = Field(min_length=6, max_length=32)
    access_token: str = Field(min_length=10, max_length=4096)
    app_secret: str = Field(min_length=10, max_length=512)
    verify_token: str = Field(min_length=16, max_length=512)


@router.post("/integrations/whatsapp", response_model=ConnectionOut, status_code=201)
def connect_whatsapp(
    body: WhatsAppIn,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> ConnectionOut:
    connected = channels.connect_whatsapp(db, auth.actor, auth.access, channels.WhatsAppSetup(**body.model_dump()))
    return _out(db, connected.view)


class MailboxIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    imap_host: str = Field(min_length=1, max_length=253)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_security: Literal["ssl", "starttls", "none"] = "ssl"
    smtp_host: str = Field(min_length=1, max_length=253)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: Literal["ssl", "starttls", "none"] = "ssl"


@router.post("/integrations/mailbox", response_model=ConnectionOut, status_code=201)
def connect_mailbox(
    body: MailboxIn,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> ConnectionOut:
    """Connect an email mailbox over IMAP/SMTP (Mixt uses neither Google Workspace nor Microsoft 365, BD-034)."""
    connected = channels.connect_mailbox(db, auth.actor, auth.access, channels.MailboxSetup(**body.model_dump()))
    return _out(db, connected.view)


class PollOut(BaseModel):
    mailboxes: int
    stored: int
    failed: int


@router.post("/integrations/{connection_id}/poll", response_model=PollOut)
def poll_mailbox(
    connection_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> PollOut:
    return PollOut(**channels.poll_now(db, auth.actor, auth.access, connection_id).__dict__)


@router.get("/integrations/{connection_id}", response_model=ConnectionOut)
def get_connection(
    connection_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> ConnectionOut:
    return _out(db, integrations.view_connection(db, auth.access, connection_id))


class CheckOut(BaseModel):
    ok: bool
    code: str | None
    detail: str
    verified_name: str | None
    quality_rating: str | None
    display_phone_number: str | None
    number_matches: bool | None


@router.post("/integrations/{connection_id}/check", response_model=CheckOut)
def check_connection(
    connection_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> CheckOut:
    return CheckOut(**channels.check_connection(db, auth.actor, auth.access, connection_id).__dict__)


class CredentialIn(BaseModel):
    kind: Literal["access_token", "app_secret", "verify_token", "client_secret", "api_key", "refresh_token", "password"]
    value: str = Field(min_length=1, max_length=4096)


@router.put("/integrations/{connection_id}/credentials", status_code=204)
def rotate_credential(
    connection_id: uuid.UUID,
    body: CredentialIn,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> None:
    integrations.set_credential(db, auth.actor, auth.access, connection_id, body.kind, body.value)


class ConfigIn(BaseModel):
    graph_api_version: str | None = Field(default=None, pattern=r"^v\d{1,3}\.\d{1,2}$")


@router.patch("/integrations/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: uuid.UUID,
    body: ConfigIn,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> ConnectionOut:
    changes = body.model_dump(exclude_none=True)
    integrations.update_config(db, auth.actor, auth.access, connection_id, changes)
    return _out(db, integrations.view_connection(db, auth.access, connection_id))


@router.post("/integrations/{connection_id}/disconnect", response_model=ConnectionOut)
def disconnect(
    connection_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> ConnectionOut:
    integrations.disconnect(db, auth.actor, auth.access, connection_id)
    return _out(db, integrations.view_connection(db, auth.access, connection_id))


class WebhookEventOut(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    attempts: int
    last_error: str | None
    received_at: datetime
    processed_at: datetime | None
    summary: str


def _summary(payload: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            field = str(change.get("field"))
            for key in ("messages", "statuses"):
                if value.get(key):
                    counts[key] = counts.get(key, 0) + len(value[key])
            if field != "messages":
                counts[field] = counts.get(field, 0) + 1
    return ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items()) or "no content"


@router.get("/integrations/{connection_id}/webhooks", response_model=list[WebhookEventOut])
def webhook_events(
    connection_id: uuid.UUID,
    status: Literal["received", "processed", "ignored", "failed"] | None = None,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> list[WebhookEventOut]:
    rows = integrations.list_webhook_events(db, auth.access, connection_id, status)
    return [
        WebhookEventOut(
            id=e.id,
            provider=e.provider,
            status=e.status,
            attempts=e.attempts,
            last_error=e.last_error,
            received_at=e.received_at,
            processed_at=e.processed_at,
            summary=_summary(e.payload),
        )
        for e in rows
    ]


@router.post("/integrations/webhooks/{event_id}/replay", status_code=204)
def replay_webhook(
    event_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> None:
    integrations.replay_webhook(db, auth.actor, auth.access, event_id)


# ------------------------------------------------------------------ templates


class TemplateOut(BaseModel):
    id: uuid.UUID
    channel_account_id: uuid.UUID
    name: str
    language: str
    category: str
    body: str
    variable_count: int
    provider_status: str
    internal_status: str
    unsupported_reason: str | None
    usable_problem: str | None
    approved_at: datetime | None
    synced_at: datetime


def template_out(template: Any, problem: str | None) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        channel_account_id=template.channel_account_id,
        name=template.name,
        language=template.language,
        category=template.category,
        body=template.body,
        variable_count=template.variable_count,
        provider_status=template.provider_status,
        internal_status=template.internal_status,
        unsupported_reason=template.unsupported_reason,
        usable_problem=problem,
        approved_at=template.approved_at,
        synced_at=template.synced_at,
    )


class SyncOut(BaseModel):
    created: int
    updated: int
    disabled: int
    needs_review: int


@router.post("/integrations/{connection_id}/templates/sync", response_model=SyncOut)
def sync_templates(
    connection_id: uuid.UUID,
    auth: AuthContext = Depends(require("integrations.manage")),
    db: Session = Depends(get_session),
) -> SyncOut:
    return SyncOut(**channels.sync_templates(db, auth.actor, auth.access, connection_id).__dict__)


@router.get("/messaging/templates", response_model=list[TemplateOut])
def list_templates(
    channel_account_id: uuid.UUID | None = None,
    _: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> list[TemplateOut]:
    return [template_out(t, channels.template_usable(t)) for t in channels.list_templates(db, channel_account_id)]


@router.post("/messaging/templates/{template_id}/approve", response_model=TemplateOut)
def approve_template(
    template_id: uuid.UUID,
    auth: AuthContext = Depends(require("messaging.templates.approve")),
    db: Session = Depends(get_session),
) -> TemplateOut:
    template = channels.approve_template(db, auth.actor, auth.access, template_id)
    return template_out(template, channels.template_usable(template))


@router.post("/messaging/templates/{template_id}/retire", response_model=TemplateOut)
def retire_template(
    template_id: uuid.UUID,
    auth: AuthContext = Depends(require("messaging.templates.approve")),
    db: Session = Depends(get_session),
) -> TemplateOut:
    template = channels.retire_template(db, auth.actor, auth.access, template_id)
    return template_out(template, channels.template_usable(template))


# ------------------------------------------------------------------ suppression list


class SuppressionOut(BaseModel):
    id: uuid.UUID
    kind: str
    value_masked: str
    reason: str
    source: str
    note: str | None
    created_at: datetime
    lifted_at: datetime | None
    lift_reason: str | None


def _suppression_out(entry: Any) -> SuppressionOut:
    return SuppressionOut(
        id=entry.id,
        kind=entry.kind,
        value_masked=crm.mask_contact_value(entry.kind, entry.value),
        reason=entry.reason,
        source=entry.source,
        note=entry.note,
        created_at=entry.created_at,
        lifted_at=entry.lifted_at,
        lift_reason=entry.lift_reason,
    )


@router.get("/messaging/suppressions", response_model=list[SuppressionOut])
def list_suppressions(
    include_lifted: bool = Query(default=False),
    auth: AuthContext = Depends(require("messaging.suppression.manage")),
    db: Session = Depends(get_session),
) -> list[SuppressionOut]:
    return [_suppression_out(e) for e in messaging.list_suppressions(db, auth.access, include_lifted)]


class SuppressionIn(BaseModel):
    kind: Literal["phone", "email"]
    value: str = Field(min_length=3, max_length=320)
    reason: Literal["manual", "complaint", "legal"]
    note: str = Field(min_length=1, max_length=1000)


@router.post("/messaging/suppressions", response_model=SuppressionOut, status_code=201)
def add_suppression(
    body: SuppressionIn,
    auth: AuthContext = Depends(require("messaging.suppression.manage")),
    db: Session = Depends(get_session),
) -> SuppressionOut:
    entry = messaging.suppress(db, auth.actor, auth.access, body.kind, body.value, body.reason, body.note)
    return _suppression_out(entry)


class LiftIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/messaging/suppressions/{entry_id}/lift", response_model=SuppressionOut)
def lift_suppression(
    entry_id: uuid.UUID,
    body: LiftIn,
    auth: AuthContext = Depends(require("messaging.suppression.manage")),
    db: Session = Depends(get_session),
) -> SuppressionOut:
    return _suppression_out(messaging.lift_suppression(db, auth.actor, auth.access, entry_id, body.reason))


@router.get("/messaging/channel-accounts", response_model=list[ChannelAccountOut])
def channel_accounts(
    _: AuthContext = Depends(require("inbox.read")), db: Session = Depends(get_session)
) -> list[ChannelAccountOut]:
    rows = [_channel_out(db, a) for a in channels.list_channel_accounts(db)]
    return [r for r in rows if r is not None]
