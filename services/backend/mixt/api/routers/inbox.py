"""Unified inbox API (Phase 3a): conversations, messages, replies, templates and live updates."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from mixt.api.background import run_after_commit
from mixt.api.deps import AuthContext, require
from mixt.api.routers.integrations import TemplateOut, template_out
from mixt.core.db import SessionScope, get_session, session_scope_factory
from mixt.core.timezones import now_utc
from mixt.modules.identity import service as identity
from mixt.modules.messaging import service as messaging

router = APIRouter(tags=["inbox"])
STREAM_POLL_SECONDS = 2.0
STREAM_LOOKBACK = timedelta(seconds=10)


class LastMessageOut(BaseModel):
    direction: str
    content_type: str
    preview: str | None
    status: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    channel: str
    channel_account_id: uuid.UUID
    channel_name: str
    channel_enabled: bool
    customer_handle: str
    customer_name: str | None
    account_id: uuid.UUID | None
    account_name: str | None
    contact_id: uuid.UUID | None
    contact_name: str | None
    status: str
    assigned_user_id: uuid.UUID | None
    assigned_name: str | None
    unread_count: int
    last_activity_at: datetime
    last_inbound_at: datetime | None
    service_window_expires_at: datetime | None
    window_open: bool
    reply_allowed: bool
    suppressed: bool
    subject: str | None
    last_message: LastMessageOut | None
    updated_at: datetime


def _preview(message: Any) -> str | None:
    if message.body_text:
        text = " ".join(message.body_text.split())
        return text if len(text) <= messaging.PREVIEW_LENGTH else text[: messaging.PREVIEW_LENGTH - 1] + "…"
    if message.media:
        return f"[{message.media.get('type', 'attachment')}]"
    return None


def conversation_out(view: messaging.ConversationView) -> ConversationOut:
    c = view.conversation
    last = view.last_message
    return ConversationOut(
        id=c.id,
        channel=view.channel,
        channel_account_id=c.channel_account_id,
        channel_name=view.channel_name,
        channel_enabled=view.channel_enabled,
        customer_handle=c.customer_handle,
        customer_name=c.customer_name,
        account_id=c.account_id,
        account_name=view.account_name,
        contact_id=c.contact_id,
        contact_name=view.contact_name,
        status=c.status,
        assigned_user_id=c.assigned_user_id,
        assigned_name=view.assigned_name,
        unread_count=c.unread_count,
        last_activity_at=c.last_activity_at,
        last_inbound_at=c.last_inbound_at,
        service_window_expires_at=c.service_window_expires_at,
        window_open=view.window_open,
        reply_allowed=view.reply_allowed,
        suppressed=view.suppressed,
        subject=c.subject,
        last_message=LastMessageOut(
            direction=last.direction,
            content_type=last.content_type,
            preview=_preview(last),
            status=last.status,
            created_at=last.created_at,
        )
        if last
        else None,
        updated_at=c.updated_at,
    )


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    sender_type: str
    sender_name: str | None
    content_type: str
    body_text: str | None
    media: dict[str, Any] | None
    email: dict[str, Any] | None
    template_id: uuid.UUID | None
    status: str
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    provider_timestamp: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None


def message_out(message: Any, names: dict[uuid.UUID, str]) -> MessageOut:
    return MessageOut(
        id=message.id,
        direction=message.direction,
        sender_type=message.sender_type,
        sender_name=names.get(message.sender_principal_id) if message.sender_principal_id else None,
        content_type=message.content_type,
        body_text=message.body_text,
        media=message.media,
        email=message.email_meta,
        template_id=message.template_id,
        status=message.status,
        failure_code=message.failure_code,
        failure_detail=message.failure_detail,
        created_at=message.created_at,
        provider_timestamp=message.provider_timestamp,
        sent_at=message.sent_at,
        delivered_at=message.delivered_at,
        read_at=message.read_at,
    )


@router.get("/inbox/conversations", response_model=list[ConversationOut])
def list_conversations(
    view: Literal["all", "mine", "unassigned", "unmatched"] = "all",
    status: Literal["active", "open", "pending_customer", "closed"] = "active",
    q: str | None = Query(default=None, max_length=100),
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> list[ConversationOut]:
    rows = messaging.list_conversations(db, auth.access, view, status, q, before, limit)
    return [conversation_out(v) for v in rows]


class SummaryOut(BaseModel):
    unread: int
    can_see_unmatched: bool
    can_assign: bool
    can_send: bool


@router.get("/inbox/summary", response_model=SummaryOut)
def summary(auth: AuthContext = Depends(require("inbox.read")), db: Session = Depends(get_session)) -> SummaryOut:
    return SummaryOut(
        unread=messaging.unread_total(db, auth.access),
        can_see_unmatched=auth.access.has_somewhere("inbox.unmatched"),
        can_assign=auth.access.has_somewhere("inbox.assign"),
        can_send=auth.access.has_somewhere("messaging.send"),
    )


class AssigneeOut(BaseModel):
    user_id: uuid.UUID
    name: str


@router.get("/inbox/assignees", response_model=list[AssigneeOut])
def assignees(_: AuthContext = Depends(require("inbox.read")), db: Session = Depends(get_session)) -> list[AssigneeOut]:
    return [AssigneeOut(user_id=i, name=n) for i, n in identity.users_with(db, "inbox.read")]


@router.get("/inbox/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: uuid.UUID,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> ConversationOut:
    return conversation_out(messaging.view_conversation(db, auth.access, conversation_id))


@router.get("/inbox/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: uuid.UUID,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> list[MessageOut]:
    rows = messaging.list_messages(db, auth.access, conversation_id, before, limit)
    names = messaging.sender_names(db, rows)
    return [message_out(m, names) for m in rows]


def _view(db: Session, auth: AuthContext, conversation_id: uuid.UUID) -> ConversationOut:
    return conversation_out(messaging.view_conversation(db, auth.access, conversation_id))


@router.post("/inbox/conversations/{conversation_id}/read", response_model=ConversationOut)
def mark_read(
    conversation_id: uuid.UUID,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> ConversationOut:
    messaging.mark_read(db, auth.actor, auth.access, conversation_id)
    return _view(db, auth, conversation_id)


class ConversationAssignIn(BaseModel):
    user_id: uuid.UUID | None


@router.post("/inbox/conversations/{conversation_id}/assign", response_model=ConversationOut)
def assign(
    conversation_id: uuid.UUID,
    body: ConversationAssignIn,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> ConversationOut:
    messaging.assign(db, auth.actor, auth.access, conversation_id, body.user_id)
    return _view(db, auth, conversation_id)


class StatusIn(BaseModel):
    status: Literal["open", "closed"]


@router.post("/inbox/conversations/{conversation_id}/status", response_model=ConversationOut)
def set_status(
    conversation_id: uuid.UUID,
    body: StatusIn,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> ConversationOut:
    messaging.set_status(db, auth.actor, auth.access, conversation_id, body.status)
    return _view(db, auth, conversation_id)


class LinkIn(BaseModel):
    account_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    save_number: bool = False


@router.post("/inbox/conversations/{conversation_id}/link", response_model=ConversationOut)
def link_customer(
    conversation_id: uuid.UUID,
    body: LinkIn,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> ConversationOut:
    messaging.link_customer(
        db, auth.actor, auth.access, conversation_id, body.account_id, body.contact_id, body.save_number
    )
    return _view(db, auth, conversation_id)


class ConversationLeadIn(BaseModel):
    guardian_first_name: str | None = Field(default=None, max_length=100)
    guardian_last_name: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    student_first_name: str | None = Field(default=None, max_length=100)


class ConversationLeadOut(BaseModel):
    lead_id: uuid.UUID
    lead_status: str
    account_id: uuid.UUID | None
    account_visible: bool
    created_account: bool
    opportunity_id: uuid.UUID | None
    conversation: ConversationOut


@router.post("/inbox/conversations/{conversation_id}/lead", response_model=ConversationLeadOut, status_code=201)
def create_lead(
    conversation_id: uuid.UUID,
    body: ConversationLeadIn,
    auth: AuthContext = Depends(require("inbox.unmatched")),
    db: Session = Depends(get_session),
) -> ConversationLeadOut:
    result = messaging.create_lead(
        db,
        auth.actor,
        auth.access,
        conversation_id,
        body.guardian_first_name,
        body.guardian_last_name,
        body.country,
        body.student_first_name,
    )
    return ConversationLeadOut(
        lead_id=result.lead.id,
        lead_status=result.lead.status,
        account_id=result.lead.account_id if result.account_visible or result.created_account else None,
        account_visible=result.account_visible,
        created_account=result.created_account,
        opportunity_id=result.opportunity_id if result.account_visible or result.created_account else None,
        conversation=_view(db, auth, conversation_id),
    )


class ConversationNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=messaging.MAX_NOTE_LENGTH)


def _one_message(db: Session, message: Any) -> MessageOut:
    names = messaging.sender_names(db, [message])
    return message_out(message, names)


@router.post("/inbox/conversations/{conversation_id}/notes", response_model=MessageOut, status_code=201)
def add_note(
    conversation_id: uuid.UUID,
    body: ConversationNoteIn,
    auth: AuthContext = Depends(require("messaging.send")),
    db: Session = Depends(get_session),
) -> MessageOut:
    return _one_message(db, messaging.add_note(db, auth.actor, auth.access, conversation_id, body.text))


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    subject: str | None = Field(default=None, max_length=500, description="Email only; defaults to Re: <subject>")


IdempotencyKey = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=100)


def _queued(db: Session, queued: messaging.Queued, background: BackgroundTasks) -> MessageOut:
    out = _one_message(db, queued.message)
    if queued.action_id is not None:
        run_after_commit(db, background, queued.action_id)  # sent straight away; the worker is the fallback
    return out


@router.post("/inbox/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=202)
def send_text(
    conversation_id: uuid.UUID,
    body: TextIn,
    background: BackgroundTasks,
    idempotency_key: str | None = IdempotencyKey,
    auth: AuthContext = Depends(require("messaging.send")),
    db: Session = Depends(get_session),
) -> MessageOut:
    queued = messaging.send_text(db, auth.actor, auth.access, conversation_id, body.text, idempotency_key, body.subject)
    return _queued(db, queued, background)


class TemplateSendIn(BaseModel):
    template_id: uuid.UUID
    variables: list[str] = Field(default_factory=list, max_length=20)


@router.post("/inbox/conversations/{conversation_id}/templates", response_model=MessageOut, status_code=202)
def send_template(
    conversation_id: uuid.UUID,
    body: TemplateSendIn,
    background: BackgroundTasks,
    idempotency_key: str | None = IdempotencyKey,
    auth: AuthContext = Depends(require("messaging.send")),
    db: Session = Depends(get_session),
) -> MessageOut:
    queued = messaging.send_template(
        db, auth.actor, auth.access, conversation_id, body.template_id, body.variables, idempotency_key
    )
    return _queued(db, queued, background)


class TemplateOptionOut(TemplateOut):
    problem: str | None


@router.get("/inbox/conversations/{conversation_id}/templates", response_model=list[TemplateOptionOut])
def template_options(
    conversation_id: uuid.UUID,
    auth: AuthContext = Depends(require("messaging.send")),
    db: Session = Depends(get_session),
) -> list[TemplateOptionOut]:
    return [
        TemplateOptionOut(**template_out(t, p).model_dump(), problem=p)
        for t, p in messaging.templates_for(db, auth.access, conversation_id)
    ]


@router.post("/inbox/messages/{message_id}/retry", response_model=MessageOut, status_code=202)
def retry(
    message_id: uuid.UUID,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require("messaging.send")),
    db: Session = Depends(get_session),
) -> MessageOut:
    return _queued(db, messaging.retry_failed(db, auth.actor, auth.access, message_id), background)


@router.get("/crm/accounts/{account_id}/conversations", response_model=list[ConversationOut])
def account_conversations(
    account_id: uuid.UUID,
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
) -> list[ConversationOut]:
    return [conversation_out(v) for v in messaging.conversations_for_account(db, auth.access, account_id)]


# ------------------------------------------------------------------ live updates (Server-Sent Events)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("/inbox/stream", response_class=StreamingResponse)
def stream(
    max_seconds: int = Query(default=55, ge=1, le=300, description="The stream ends after this; clients reconnect"),
    auth: AuthContext = Depends(require("inbox.read")),
    db: Session = Depends(get_session),
    scope: SessionScope = Depends(session_scope_factory),
) -> StreamingResponse:
    """Server-Sent Events: ``conversation`` events name conversations that changed (refetch them)."""
    access = auth.access
    # The request's session would otherwise stay in a transaction (holding a pooled connection)
    # until the stream ends; each poll below uses its own short session instead.
    db.commit()

    def changes(since: datetime) -> list[tuple[uuid.UUID, datetime]]:
        with scope() as session:
            return messaging.changes_since(session, access, since)

    async def events() -> AsyncIterator[str]:
        deadline = time.monotonic() + max_seconds
        seen: dict[uuid.UUID, datetime] = {}
        since = now_utc() - STREAM_LOOKBACK
        yield "retry: 3000\n\n"
        yield _sse("ready", {"at": now_utc().isoformat()})
        while True:
            for conversation_id, updated_at in await run_in_threadpool(changes, since - STREAM_LOOKBACK):
                if seen.get(conversation_id) != updated_at:
                    seen[conversation_id] = updated_at
                    yield _sse("conversation", {"id": str(conversation_id), "updated_at": updated_at.isoformat()})
                since = max(since, updated_at)
            if time.monotonic() >= deadline:
                break
            yield ": keep-alive\n\n"
            await asyncio.sleep(min(STREAM_POLL_SECONDS, max(deadline - time.monotonic(), 0)))
        yield _sse("bye", {})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )
