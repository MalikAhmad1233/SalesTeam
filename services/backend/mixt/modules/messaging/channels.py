"""Channel accounts and WhatsApp templates (docs/07 §2).

A WhatsApp connection is an integration connection (encrypted access token, app secret and
webhook verify token) plus one channel account for its registered ``phone_number_id``. Templates
are synced from Meta; staff can use one only after Meta **and** a Mixt approver have approved it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.config import get_config
from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.normalize import normalize_phone
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.integrations import service as integrations
from mixt.modules.messaging import whatsapp
from mixt.modules.messaging.models import ChannelAccount, MessageTemplate
from mixt.modules.settings import service as settings

WHATSAPP = "meta_whatsapp_cloud"
MIN_VERIFY_TOKEN_LENGTH = 16


@dataclass
class WhatsAppSetup:
    display_name: str
    graph_api_version: str
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    access_token: str
    app_secret: str
    verify_token: str


@dataclass(frozen=True)
class ConnectedChannel:
    view: integrations.ConnectionView
    channel_account: ChannelAccount


def _validate(data: WhatsAppSetup) -> str:
    if not whatsapp.VERSION_RE.match(data.graph_api_version.strip()):
        raise ValidationFailed(
            "INVALID_GRAPH_VERSION",
            "Give the Graph API version your Meta app uses, like v21.0 (see the app dashboard).",
        )
    for label, value in (("WhatsApp Business Account id", data.waba_id), ("phone number id", data.phone_number_id)):
        if not whatsapp.ID_RE.match(value.strip()):
            raise ValidationFailed(
                "INVALID_PROVIDER_ID", f"The {label} should be the number shown in Meta's dashboard."
            )
    if len(data.verify_token.strip()) < MIN_VERIFY_TOKEN_LENGTH:
        raise ValidationFailed(
            "VERIFY_TOKEN_TOO_SHORT",
            f"Use a random webhook verify token of at least {MIN_VERIFY_TOKEN_LENGTH} characters.",
        )
    return normalize_phone(data.display_phone_number)


def connect_whatsapp(db: Session, actor: Actor, access: Access, data: WhatsAppSetup) -> ConnectedChannel:
    """Store a WhatsApp Cloud API connection. It stays 'pending' until a check or a webhook succeeds."""
    access.require_somewhere("integrations.manage")
    address = _validate(data)
    phone_number_id = data.phone_number_id.strip()
    existing = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == "whatsapp", ChannelAccount.external_id == phone_number_id
        )
    )
    if existing is not None and integrations.get_connection(db, existing.connection_id).status != "disconnected":
        raise Conflict("CHANNEL_ALREADY_CONNECTED", "This WhatsApp number is already connected. Disconnect it first.")
    connection = integrations.create_connection(
        db,
        actor,
        access,
        WHATSAPP,
        data.display_name,
        {
            "graph_api_version": data.graph_api_version.strip(),
            "waba_id": data.waba_id.strip(),
            "phone_number_id": phone_number_id,
        },
        {"access_token": data.access_token, "app_secret": data.app_secret, "verify_token": data.verify_token},
    )
    if existing is not None:  # reconnecting keeps the number's conversation history
        existing.connection_id, existing.address, existing.status = connection.id, address, "active"
        existing.display_name = data.display_name.strip()
        account = existing
    else:
        account = ChannelAccount(
            channel="whatsapp",
            connection_id=connection.id,
            external_id=phone_number_id,
            display_name=data.display_name.strip(),
            address=address,
        )
        db.add(account)
    db.flush()
    return ConnectedChannel(integrations.view_connection(db, access, connection.id), account)


def channel_account_for(db: Session, connection_id: uuid.UUID) -> ChannelAccount | None:
    return db.scalar(select(ChannelAccount).where(ChannelAccount.connection_id == connection_id))


def whatsapp_account(db: Session, connection_id: uuid.UUID, phone_number_id: str) -> ChannelAccount | None:
    return db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == "whatsapp",
            ChannelAccount.external_id == phone_number_id,
            ChannelAccount.connection_id == connection_id,
        )
    )


def list_channel_accounts(db: Session) -> list[ChannelAccount]:
    return list(db.scalars(select(ChannelAccount).order_by(ChannelAccount.created_at)))


def graph_config(db: Session, connection: integrations.Connection) -> whatsapp.GraphConfig:
    token = integrations.secret(db, connection.id, "access_token")
    if token is None or connection.status == "disconnected":
        raise whatsapp.WhatsAppError(
            whatsapp.ErrorKind("CONNECTION_PROBLEM", False, True), "The WhatsApp connection has no access token."
        )
    base_url = get_config().whatsapp_graph_base_url or whatsapp.GRAPH_BASE_URL  # override: local/test only
    return whatsapp.GraphConfig(str(connection.config.get("graph_api_version", "")), token, base_url.rstrip("/"))


def enabled_numbers(db: Session) -> set[str]:
    """Numbers switched on by ``channels.whatsapp.numbers`` (globally or for any market; Q-COM-01)."""
    values: list[Any] = list(settings.get_value(db, "channels.whatsapp.numbers") or [])
    for row in settings.list_scoped_overrides(db, "channels.whatsapp.numbers"):
        values.extend(row.value or [])
    enabled: set[str] = set()
    for value in values:
        try:
            enabled.add(normalize_phone(str(value)))
        except ValidationFailed:
            continue
    return enabled


def is_enabled(db: Session, account: ChannelAccount) -> bool:
    if account.status != "active" or account.address is None:
        return False
    if account.channel == "whatsapp":
        return account.address in enabled_numbers(db)
    return False


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    code: str | None
    detail: str
    verified_name: str | None = None
    quality_rating: str | None = None
    display_phone_number: str | None = None
    number_matches: bool | None = None


def check_whatsapp(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID) -> CheckResult:
    """Call the Graph API with the stored token to confirm the connection works."""
    access.require_somewhere("integrations.manage")
    connection = integrations.get_connection(db, connection_id)
    account = channel_account_for(db, connection.id)
    if connection.provider != WHATSAPP or account is None:
        raise NotFound("CONNECTION_NOT_FOUND", "WhatsApp connection not found.")
    try:
        info = whatsapp.phone_number_info(graph_config(db, connection), account.external_id)
    except whatsapp.WhatsAppError as exc:
        if exc.kind.connection_problem:
            integrations.mark_error(db, connection, f"{exc.kind.code}: {exc.detail}")
        audit.record(
            db,
            actor,
            "integration_checked",
            "integration_connection",
            connection.id,
            {"ok": False, "code": exc.kind.code},
        )
        return CheckResult(False, exc.kind.code, exc.detail)
    integrations.mark_success(db, connection)
    shown = info.get("display_phone_number")
    matches = None
    if shown:
        try:
            matches = normalize_phone("+" + str(shown).lstrip("+")) == account.address
        except ValidationFailed:
            matches = False
    audit.record(db, actor, "integration_checked", "integration_connection", connection.id, {"ok": True})
    return CheckResult(
        True,
        None,
        "Connected." if matches is not False else "Connected, but Meta shows a different number than the one entered.",
        info.get("verified_name"),
        info.get("quality_rating"),
        shown,
        matches,
    )


# ------------------------------------------------------------------ templates


@dataclass(frozen=True)
class SyncResult:
    created: int
    updated: int
    disabled: int
    needs_review: int


def sync_templates(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID) -> SyncResult:
    """Fetch the WhatsApp Business Account's templates and update Mixt's copies.

    A template whose wording changed at Meta goes back to 'not reviewed' so a person approves the
    new wording; templates missing from Meta are marked disabled.
    """
    access.require_somewhere("integrations.manage")
    connection = integrations.get_connection(db, connection_id)
    account = channel_account_for(db, connection.id)
    if connection.provider != WHATSAPP or account is None:
        raise NotFound("CONNECTION_NOT_FOUND", "WhatsApp connection not found.")
    try:
        remote = whatsapp.fetch_templates(graph_config(db, connection), str(connection.config.get("waba_id", "")))
    except whatsapp.WhatsAppError as exc:
        if exc.kind.connection_problem:
            integrations.mark_error(db, connection, f"{exc.kind.code}: {exc.detail}")
        raise ValidationFailed("TEMPLATE_SYNC_FAILED", f"Meta refused the request: {exc.detail}") from exc
    integrations.mark_success(db, connection)
    existing = {
        (t.name, t.language): t
        for t in db.scalars(select(MessageTemplate).where(MessageTemplate.channel_account_id == account.id))
    }
    seen: set[tuple[str, str]] = set()
    created = updated = needs_review = 0
    for item in remote:
        name, language = str(item.get("name") or ""), str(item.get("language") or "")
        category = str(item.get("category") or "").lower()
        if not name or not language or category not in ("marketing", "utility", "authentication"):
            continue
        components = [c for c in item.get("components") or [] if isinstance(c, dict)]
        facts = whatsapp.template_facts(category, components)
        status = whatsapp.PROVIDER_TEMPLATE_STATUS.get(str(item.get("status") or "").upper(), "disabled")
        seen.add((name, language))
        template = existing.get((name, language))
        if template is None:
            db.add(
                MessageTemplate(
                    channel_account_id=account.id,
                    name=name,
                    language=language,
                    category=category,
                    body=facts.body,
                    components=components,
                    variable_count=facts.variable_count,
                    unsupported_reason=facts.unsupported_reason,
                    provider_template_id=str(item.get("id") or "") or None,
                    provider_status=status,
                )
            )
            created += 1
            continue
        changed_wording = template.body != facts.body or template.components != components
        if (changed_wording or template.category != category) and template.internal_status == "approved":
            template.internal_status, template.approved_by, template.approved_at = "not_reviewed", None, None
            needs_review += 1
        template.category, template.body, template.components = category, facts.body, components
        template.variable_count, template.unsupported_reason = facts.variable_count, facts.unsupported_reason
        template.provider_template_id = str(item.get("id") or "") or template.provider_template_id
        template.provider_status, template.synced_at = status, now_utc()
        updated += 1
    disabled = 0
    for key, template in existing.items():
        if key not in seen and template.provider_status != "disabled":
            template.provider_status, template.synced_at = "disabled", now_utc()
            disabled += 1
    db.flush()
    result = SyncResult(created, updated, disabled, needs_review)
    audit.record(db, actor, "templates_synced", "integration_connection", connection.id, result.__dict__)
    return result


def list_templates(db: Session, channel_account_id: uuid.UUID | None = None) -> list[MessageTemplate]:
    query = select(MessageTemplate).order_by(MessageTemplate.name, MessageTemplate.language)
    if channel_account_id is not None:
        query = query.where(MessageTemplate.channel_account_id == channel_account_id)
    return list(db.scalars(query))


def get_template(db: Session, template_id: uuid.UUID) -> MessageTemplate:
    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise NotFound("TEMPLATE_NOT_FOUND", "Template not found.")
    return template


def template_usable(template: MessageTemplate) -> str | None:
    """Why staff cannot send this template now, or None when they can."""
    if template.provider_status != "approved":
        return f"Meta's status is '{template.provider_status}'."
    if template.internal_status != "approved":
        return "Not approved for use at Mixt yet." if template.internal_status == "not_reviewed" else "Retired."
    if template.unsupported_reason:
        return f"Mixt cannot fill this template yet: {template.unsupported_reason}."
    return None


def approve_template(db: Session, actor: Actor, access: Access, template_id: uuid.UUID) -> MessageTemplate:
    access.require_somewhere("messaging.templates.approve")
    template = get_template(db, template_id)
    if template.provider_status != "approved":
        raise ValidationFailed("TEMPLATE_NOT_APPROVED_BY_META", "Meta has not approved this template.")
    if template.unsupported_reason:
        raise ValidationFailed(
            "TEMPLATE_UNSUPPORTED", f"Mixt cannot fill this template: {template.unsupported_reason}."
        )
    template.internal_status, template.approved_by, template.approved_at = "approved", actor.principal_id, now_utc()
    db.flush()
    audit.record(
        db,
        actor,
        "template_approved",
        "message_template",
        template.id,
        {"name": template.name, "language": template.language, "category": template.category},
    )
    return template


def retire_template(db: Session, actor: Actor, access: Access, template_id: uuid.UUID) -> MessageTemplate:
    access.require_somewhere("messaging.templates.approve")
    template = get_template(db, template_id)
    template.internal_status, template.approved_by, template.approved_at = "retired", None, None
    db.flush()
    audit.record(db, actor, "template_retired", "message_template", template.id, {"name": template.name})
    return template


def apply_template_update(db: Session, account: ChannelAccount, update: whatsapp.TemplateUpdate) -> bool:
    template = db.scalar(
        select(MessageTemplate).where(
            MessageTemplate.channel_account_id == account.id,
            MessageTemplate.provider_template_id == update.template_id,
        )
    )
    if template is None:
        return False
    status = whatsapp.PROVIDER_TEMPLATE_STATUS.get(update.event.upper())
    if status is None:
        return False
    template.provider_status, template.synced_at = status, now_utc()
    db.flush()
    return True
