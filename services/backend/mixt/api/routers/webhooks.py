"""Inbound provider webhooks (docs/07 §1): verify first, store, answer quickly, process later.

Served outside ``/api`` (no session, no CSRF): authenticity comes from the provider's signature.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from mixt.api import throttle
from mixt.api.background import run_after_commit
from mixt.core.db import get_session
from mixt.core.logging import get_logger
from mixt.modules.integrations import service as integrations
from mixt.modules.messaging import channels, whatsapp

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger("mixt.webhooks")
MAX_BODY_BYTES = 1_000_000


def _connection(db: Session, connection_id: uuid.UUID) -> integrations.Connection | None:
    connection = db.get(integrations.Connection, connection_id)
    if connection is None or connection.provider != channels.WHATSAPP or connection.status == "disconnected":
        return None
    return connection


@router.get("/whatsapp/{connection_id}", include_in_schema=False)
def whatsapp_verify(
    connection_id: uuid.UUID,
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge", max_length=200),
    db: Session = Depends(get_session),
) -> Response:
    """Meta's subscription handshake: echo the challenge only when the verify token matches."""
    connection = _connection(db, connection_id)
    expected = integrations.secret(db, connection.id, "verify_token") if connection else None
    if connection is None or expected is None or not whatsapp.verify_subscription(mode, token, expected):
        if connection is not None:
            integrations.record_rejected_webhook(db, connection.id)
        return Response(status_code=403)
    connection.config = {**connection.config, "webhook_verified": True}
    return Response(content=challenge or "", media_type="text/plain")


def _receive(db: Session, connection_id: uuid.UUID, body: bytes, signature: str | None) -> tuple[int, uuid.UUID | None]:
    connection = _connection(db, connection_id)
    if connection is None:
        return 404, None
    app_secret = integrations.secret(db, connection.id, "app_secret")
    if app_secret is None or not whatsapp.verify_signature(app_secret, body, signature):
        integrations.record_rejected_webhook(db, connection.id)
        log.warning("webhook_rejected", provider=connection.provider, reason="signature")
        return 401, None
    try:
        payload = json.loads(body)
    except ValueError:
        integrations.record_rejected_webhook(db, connection.id)
        return 400, None
    if not isinstance(payload, dict):
        return 400, None
    stored = integrations.store_webhook(db, connection, whatsapp.event_id(body), payload)
    return 200, stored.action_id if stored else None  # None: a redelivery of something already stored


@router.post("/whatsapp/{connection_id}", include_in_schema=False)
async def whatsapp_receive(
    connection_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
) -> Response:
    decision = await run_in_threadpool(throttle.check, "webhook_per_connection", str(connection_id))
    if not decision.allowed:
        return Response(status_code=429, headers={"Retry-After": str(decision.retry_after_seconds)})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=413)
    status, action_id = await run_in_threadpool(
        _receive, db, connection_id, body, request.headers.get("x-hub-signature-256")
    )
    if action_id is not None:
        await run_in_threadpool(run_after_commit, db, background, action_id)  # processed straight away
    return Response(status_code=status)
