"""Channel accounts and WhatsApp templates (docs/07 §2).

A WhatsApp connection is an integration connection (encrypted access token, app secret and
webhook verify token) plus one channel account for its registered ``phone_number_id``. Templates
are synced from Meta; staff can use one only after Meta **and** a Mixt approver have approved it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.config import get_config
from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.integrations import service as integrations
from mixt.modules.messaging import email_channel, whatsapp
from mixt.modules.messaging.models import ChannelAccount, MessageTemplate
from mixt.modules.settings import service as settings

WHATSAPP = "meta_whatsapp_cloud"
MAILBOX = "imap_smtp"
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


def enabled_mailboxes(db: Session) -> set[str]:
    """Mailboxes switched on: ``channels.email.provider = imap_smtp`` and listed in ``channels.email.mailboxes``."""
    if settings.get_value(db, "channels.email.provider") != MAILBOX:
        return set()
    values: list[Any] = list(settings.get_value(db, "channels.email.mailboxes") or [])
    for row in settings.list_scoped_overrides(db, "channels.email.mailboxes"):
        values.extend(row.value or [])
    enabled: set[str] = set()
    for value in values:
        try:
            enabled.add(normalize_email(str(value)))
        except ValidationFailed:
            continue
    return enabled


def is_enabled(db: Session, account: ChannelAccount) -> bool:
    if account.status != "active" or account.address is None:
        return False
    if account.channel == "whatsapp":
        return account.address in enabled_numbers(db)
    if account.channel == "email":
        return account.address in enabled_mailboxes(db)
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


def check_connection(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID) -> CheckResult:
    """Confirm a connection works with its stored secrets (WhatsApp: Graph API; mailbox: IMAP and SMTP sign-in)."""
    access.require_somewhere("integrations.manage")
    if integrations.get_connection(db, connection_id).provider == MAILBOX:
        return _check_mailbox(db, actor, connection_id)
    return check_whatsapp(db, actor, access, connection_id)


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


# ------------------------------------------------------------------ email mailboxes (IMAP/SMTP, BD-034)


@dataclass
class MailboxSetup:
    display_name: str
    address: str
    username: str
    password: str
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str


_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def _validate_mailbox(data: MailboxSetup) -> str:
    address = normalize_email(data.address)
    deployed = get_config().env.value in ("staging", "production")
    for label, host, port, security in (
        ("IMAP", data.imap_host, data.imap_port, data.imap_security),
        ("SMTP", data.smtp_host, data.smtp_port, data.smtp_security),
    ):
        if not _HOST_RE.match(host.strip()):
            raise ValidationFailed("INVALID_HOST", f"The {label} server name is not valid.")
        if not 1 <= port <= 65535:
            raise ValidationFailed("INVALID_PORT", f"The {label} port is not valid.")
        if security not in email_channel.SECURITY_MODES or (security == "none" and deployed):
            raise ValidationFailed(
                "INSECURE_MAIL_CONNECTION", f"The {label} connection must be encrypted (TLS or STARTTLS)."
            )
    if not data.username.strip() or not data.password:
        raise ValidationFailed("CREDENTIALS_REQUIRED", "Give the mailbox user name and its app password.")
    return address


def connect_mailbox(db: Session, actor: Actor, access: Access, data: MailboxSetup) -> ConnectedChannel:
    """Store an IMAP/SMTP mailbox. Its password is encrypted; the first check starts from 'now'."""
    access.require_somewhere("integrations.manage")
    address = _validate_mailbox(data)
    existing = db.scalar(
        select(ChannelAccount).where(ChannelAccount.channel == "email", ChannelAccount.external_id == address)
    )
    if existing is not None and integrations.get_connection(db, existing.connection_id).status != "disconnected":
        raise Conflict("CHANNEL_ALREADY_CONNECTED", "This mailbox is already connected. Disconnect it first.")
    connection = integrations.create_connection(
        db,
        actor,
        access,
        MAILBOX,
        data.display_name,
        {
            "address": address,
            "username": data.username.strip(),
            "imap_host": data.imap_host.strip().lower(),
            "imap_port": data.imap_port,
            "imap_security": data.imap_security,
            "smtp_host": data.smtp_host.strip().lower(),
            "smtp_port": data.smtp_port,
            "smtp_security": data.smtp_security,
        },
        {"password": data.password},
    )
    if existing is not None:  # reconnecting keeps the mailbox's conversation history
        existing.connection_id, existing.status, existing.sync_state = connection.id, "active", None
        existing.display_name = data.display_name.strip()
        account = existing
    else:
        account = ChannelAccount(
            channel="email",
            connection_id=connection.id,
            external_id=address,
            display_name=data.display_name.strip(),
            address=address,
        )
        db.add(account)
    db.flush()
    return ConnectedChannel(integrations.view_connection(db, access, connection.id), account)


def mailbox_config(
    db: Session, connection: integrations.Connection, account: ChannelAccount
) -> email_channel.MailboxConfig:
    password = integrations.secret(db, connection.id, "password")
    if password is None or connection.status == "disconnected":
        raise email_channel.MailError(
            email_channel.MailErrorKind("CONNECTION_PROBLEM", False, True), "The mailbox has no password stored."
        )
    c = connection.config
    return email_channel.MailboxConfig(
        address=str(account.address),
        display_name=account.display_name,
        username=str(c.get("username", "")),
        password=password,
        imap_host=str(c.get("imap_host", "")),
        imap_port=int(c.get("imap_port", 993)),
        imap_security=str(c.get("imap_security", "ssl")),
        smtp_host=str(c.get("smtp_host", "")),
        smtp_port=int(c.get("smtp_port", 465)),
        smtp_security=str(c.get("smtp_security", "ssl")),
    )


def _check_mailbox(db: Session, actor: Actor, connection_id: uuid.UUID) -> CheckResult:
    connection = integrations.get_connection(db, connection_id)
    account = channel_account_for(db, connection.id)
    if account is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Mailbox not found.")
    try:
        email_channel.check(mailbox_config(db, connection, account))
    except email_channel.MailError as exc:
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
    audit.record(db, actor, "integration_checked", "integration_connection", connection.id, {"ok": True})
    return CheckResult(True, None, "Connected: signed in to IMAP and SMTP.")


@dataclass
class PollResult:
    mailboxes: int = 0
    stored: int = 0
    failed: int = 0


def poll_mailboxes(
    db: Session, now: datetime | None = None, force: bool = False, connection_id: uuid.UUID | None = None
) -> PollResult:
    """Read new mail from every connected mailbox that is due (worker). Each email is stored as a
    verified inbound event, so processing, retries and replay work as for webhooks."""
    now = now or now_utc()
    interval = timedelta(seconds=get_config().email_poll_interval_seconds)
    result = PollResult()
    for connection in integrations.connections_for(db, MAILBOX):
        if connection_id is not None and connection.id != connection_id:
            continue
        account = channel_account_for(db, connection.id)
        if account is None or account.status != "active" or (connection.status == "error" and not force):
            continue
        state = dict(account.sync_state or {})
        last_polled = state.get("last_polled_at")
        if not force and last_polled and datetime.fromisoformat(last_polled) + interval > now:
            continue
        result.mailboxes += 1
        try:
            fetched = email_channel.fetch_new(mailbox_config(db, connection, account), state or None)
        except email_channel.MailError as exc:
            result.failed += 1
            if exc.kind.connection_problem:
                integrations.mark_error(db, connection, f"{exc.kind.code}: {exc.detail}")
            account.sync_state = {**state, "last_polled_at": now.isoformat(), "last_error": exc.detail[:500]}
            db.flush()
            continue
        started = state.get("started_at") or now.isoformat()
        for uid, raw in fetched.messages:
            parsed = email_channel.parse(raw)
            if fetched.resynced and parsed.get("date") and str(parsed["date"]) < started:
                continue  # after a mailbox rebuild: mail from before Mixt was connected is not imported
            stored = integrations.store_webhook(
                db, connection, email_channel.event_id(str(connection.id), parsed), {**parsed, "uid": uid}
            )
            result.stored += 1 if stored else 0
        account.sync_state = {
            "started_at": started,
            "uidvalidity": fetched.uidvalidity,
            "last_uid": fetched.last_uid,
            "last_polled_at": now.isoformat(),
            "last_error": None,
        }
        integrations.mark_success(db, connection)
        db.flush()
    return result


def poll_now(db: Session, actor: Actor, access: Access, connection_id: uuid.UUID) -> PollResult:
    """Read a mailbox straight away (admin button), instead of waiting for the worker's next check."""
    access.require_somewhere("integrations.manage")
    connection = integrations.get_connection(db, connection_id)
    if connection.provider != MAILBOX:
        raise NotFound("CONNECTION_NOT_FOUND", "Mailbox not found.")
    result = poll_mailboxes(db, force=True, connection_id=connection.id)
    audit.record(db, actor, "mailbox_checked", "integration_connection", connection.id, {"stored": result.stored})
    return result
