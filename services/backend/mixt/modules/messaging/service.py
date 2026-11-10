"""Conversations, messages and the suppression list: the unified inbox (docs/07 §2, docs/09 §4).

Rules enforced on every outbound message (docs/07 §2, docs/08):
- the channel's number must be switched on in ``channels.whatsapp.numbers`` (Q-COM-01);
- nothing goes to a number on the suppression list (opt-out keyword, complaint, legal, manual);
- students are messaged directly only when ``messaging.student_direct_contact`` allows it;
- free-form WhatsApp text only inside the 24-hour customer-service window; outside it, only a
  template approved by Meta **and** by Mixt;
- a template needs the customer's consent: service messages for utility templates, WhatsApp
  marketing consent for marketing templates. A conversation not linked to a contact gets none.

Outbound messages are queued and sent by the worker (with retries and backoff); the API also
tries straight away after the request commits. Every send is audited without its text.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR, Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access, system_access
from mixt.modules.integrations import service as integrations
from mixt.modules.leads import service as leads
from mixt.modules.messaging import channels, whatsapp
from mixt.modules.messaging.models import (
    ChannelAccount,
    Conversation,
    Message,
    MessageStatusEvent,
    MessageTemplate,
    SuppressionEntry,
)
from mixt.modules.settings import service as settings

SERVICE_WINDOW = timedelta(hours=24)
SEND_ACTION = "messaging.send"
MAX_NOTE_LENGTH = 4000
MAX_TEMPLATE_VARIABLE_LENGTH = 1000
PREVIEW_LENGTH = 140
_STATUS_RANK = {"queued": 0, "sending": 1, "sent": 2, "delivered": 3, "read": 4}
_PUNCTUATION = re.compile(r"[\s.!?,;:'\"()\[\]{}…؟،]+")
_SYSTEM_CRM = ("crm.accounts.read_all", "crm.accounts.read", "crm.consents.record")


def register() -> None:
    integrations.register_webhook_processor(channels.WHATSAPP, process_whatsapp)
    events.register_action_handler(SEND_ACTION, _send_action, on_dead_letter=_send_gave_up)


# ------------------------------------------------------------------ suppression


def _suppressed(db: Session, kind: str, value: str) -> SuppressionEntry | None:
    return db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.kind == kind, SuppressionEntry.value == value, SuppressionEntry.lifted_at.is_(None)
        )
    )


def is_suppressed(db: Session, kind: str, value: str) -> bool:
    return _suppressed(db, kind, value) is not None


def _normalise(kind: str, value: str) -> str:
    if kind == "phone":
        return normalize_phone(value)
    if kind == "email":
        return normalize_email(value)
    raise ValidationFailed("INVALID_KIND", "Kind must be phone or email.")


def _add_suppression(
    db: Session, actor: Actor, kind: str, value: str, reason: str, source: str, note: str | None
) -> SuppressionEntry | None:
    entry_id = db.scalar(
        insert(SuppressionEntry)
        .values(kind=kind, value=value, reason=reason, source=source, note=note, created_by=actor.principal_id)
        .on_conflict_do_nothing(index_elements=["kind", "value"], index_where=SuppressionEntry.lifted_at.is_(None))
        .returning(SuppressionEntry.id)
    )
    if entry_id is None:
        return None
    audit.record(
        db,
        actor,
        "suppression_added",
        "suppression_entry",
        entry_id,
        {"kind": kind, "value": crm.mask_contact_value(kind, value), "reason": reason, "source": source},
    )
    return db.get(SuppressionEntry, entry_id)


def suppress(
    db: Session, actor: Actor, access: Access, kind: str, value: str, reason: str, note: str
) -> SuppressionEntry:
    access.require_somewhere("messaging.suppression.manage")
    if reason not in ("manual", "complaint", "legal"):
        raise ValidationFailed("INVALID_REASON", "Reason must be manual, complaint or legal.")
    if not note.strip():
        raise ValidationFailed("NOTE_REQUIRED", "Say why messages to this number or address must stop.")
    normalised = _normalise(kind, value)
    entry = _add_suppression(db, actor, kind, normalised, reason, "staff", note.strip())
    if entry is None:
        raise Conflict("ALREADY_SUPPRESSED", "Messages to this number or address are already blocked.")
    return entry


def lift_suppression(db: Session, actor: Actor, access: Access, entry_id: uuid.UUID, reason: str) -> SuppressionEntry:
    access.require_somewhere("messaging.suppression.manage")
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None or entry.lifted_at is not None:
        raise NotFound("SUPPRESSION_NOT_FOUND", "No active block with this id.")
    if not reason.strip():
        raise ValidationFailed("REASON_REQUIRED", "Say why messages may be sent again (e.g. the customer asked).")
    entry.lifted_at, entry.lifted_by, entry.lift_reason = now_utc(), actor.principal_id, reason.strip()
    db.flush()
    audit.record(
        db,
        actor,
        "suppression_lifted",
        "suppression_entry",
        entry.id,
        {"kind": entry.kind, "value": crm.mask_contact_value(entry.kind, entry.value), "reason": reason.strip()},
    )
    return entry


def list_suppressions(db: Session, access: Access, include_lifted: bool = False) -> list[SuppressionEntry]:
    access.require_somewhere("messaging.suppression.manage")
    query = select(SuppressionEntry).order_by(SuppressionEntry.created_at.desc()).limit(500)
    if not include_lifted:
        query = query.where(SuppressionEntry.lifted_at.is_(None))
    return list(db.scalars(query))


# ------------------------------------------------------------------ inbound processing


def _keyword(text: str | None) -> str:
    return _PUNCTUATION.sub(" ", (text or "")).strip().casefold()


def _matches(text: str | None, setting_key: str, db: Session) -> bool:
    words = {_keyword(w) for w in settings.get_value(db, setting_key) or []}
    return bool(text) and _keyword(text) in words


def _customer_handle(wa_id: str) -> str:
    try:
        return normalize_phone("+" + wa_id.lstrip("+"))
    except ValidationFailed:
        return "+" + "".join(ch for ch in wa_id if ch.isdigit())


def _conversation_for(db: Session, account: ChannelAccount, handle: str) -> Conversation:
    db.execute(
        insert(Conversation)
        .values(channel_account_id=account.id, customer_handle=handle)
        .on_conflict_do_nothing(index_elements=["channel_account_id", "customer_handle"])
    )
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.channel_account_id == account.id, Conversation.customer_handle == handle)
        .with_for_update()
    )
    if conversation is None:  # pragma: no cover - the insert above guarantees a row
        raise NotFound("CONVERSATION_NOT_FOUND", "Conversation not found.")
    return conversation


def _match_customer(db: Session, conversation: Conversation) -> None:
    """Link a new conversation to the one household that already has this number (never a guess)."""
    if conversation.account_id is not None:
        return
    matches = crm.accounts_matching_contact_points(db, [("whatsapp", conversation.customer_handle)])
    if len(matches) != 1:
        return
    conversation.account_id = matches[0]
    conversation.contact_id = crm.contact_with_point(db, matches[0], "whatsapp", conversation.customer_handle)
    if conversation.assigned_user_id is None:
        conversation.assigned_user_id = crm.account_for_system(db, matches[0]).owner_user_id


def _system_note(db: Session, conversation: Conversation, text: str) -> None:
    db.add(
        Message(
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            direction="internal",
            sender_type="system",
            content_type="note",
            body_text=text,
            status="recorded",
        )
    )


def _record_messaging_consent(db: Session, conversation: Conversation, status: str, evidence: dict[str, Any]) -> None:
    if conversation.contact_id is None:
        return
    access = system_access(*_SYSTEM_CRM)
    for purpose in ("marketing_whatsapp", "service_messages"):
        if crm.latest_consent_status(db, conversation.contact_id, purpose) == "granted":
            crm.record_consent(
                db,
                SYSTEM_ACTOR,
                access,
                conversation.contact_id,
                purpose,
                status,
                "consent",
                "whatsapp_keyword",
                evidence,
            )


def _apply_keywords(db: Session, conversation: Conversation, msg: whatsapp.InboundMessage) -> None:
    if msg.content_type != "text":
        return
    if _matches(msg.text, "messaging.opt_out_keywords", db):
        added = _add_suppression(
            db, SYSTEM_ACTOR, "phone", conversation.customer_handle, "opt_out", "whatsapp_keyword", None
        )
        _record_messaging_consent(
            db, conversation, "withdrawn", {"keyword": (msg.text or "").strip()[:40], "message_id": msg.message_id}
        )
        if added is not None:
            _system_note(
                db,
                conversation,
                "The customer asked to stop messages. This number is now blocked; "
                "a manager can allow messages again if the customer asks.",
            )
    elif _matches(msg.text, "messaging.opt_in_keywords", db):
        entry = _suppressed(db, "phone", conversation.customer_handle)
        if entry is not None and entry.reason == "opt_out":
            entry.lifted_at, entry.lifted_by = now_utc(), SYSTEM_ACTOR.principal_id
            entry.lift_reason = "The customer sent an opt-in keyword."
            audit.record(
                db, SYSTEM_ACTOR, "suppression_lifted", "suppression_entry", entry.id, {"reason": "opt_in_keyword"}
            )
            _system_note(
                db,
                conversation,
                "The customer asked to receive messages again. The block is lifted; marketing still needs consent.",
            )


def _store_inbound(db: Session, account: ChannelAccount, msg: whatsapp.InboundMessage) -> bool:
    handle = _customer_handle(msg.wa_id)
    conversation = _conversation_for(db, account, handle)
    message_id = db.scalar(
        insert(Message)
        .values(
            conversation_id=conversation.id,
            channel_account_id=account.id,
            direction="inbound",
            sender_type="customer",
            content_type=msg.content_type,
            body_text=msg.text,
            media=msg.media,
            provider_message_id=msg.message_id,
            provider_timestamp=msg.timestamp,
            status="received",
        )
        .on_conflict_do_nothing(index_elements=["channel_account_id", "provider_message_id"])
        .returning(Message.id)
    )
    if message_id is None:
        return False  # already stored (Meta redelivers)
    if msg.profile_name:
        conversation.customer_name = msg.profile_name[:200]
    window = msg.timestamp + SERVICE_WINDOW
    if conversation.service_window_expires_at is None or window > conversation.service_window_expires_at:
        conversation.service_window_expires_at = window
    if conversation.last_inbound_at is None or msg.timestamp > conversation.last_inbound_at:
        conversation.last_inbound_at = msg.timestamp
    conversation.last_activity_at = now_utc()
    conversation.unread_count += 1
    conversation.status = "open"
    _match_customer(db, conversation)
    _apply_keywords(db, conversation, msg)
    db.flush()
    events.emit(
        db,
        SYSTEM_ACTOR,
        "conversation.message_received",
        "conversation",
        conversation.id,
        {"channel": account.channel, "message_id": message_id, "matched": conversation.account_id is not None},
        conversation.account_id,
    )
    return True


def _apply_status(db: Session, account: ChannelAccount, update_: whatsapp.StatusUpdate) -> bool:
    message = db.scalar(
        select(Message)
        .where(Message.channel_account_id == account.id, Message.provider_message_id == update_.message_id)
        .with_for_update()
    )
    if message is None or update_.status not in ("sent", "delivered", "read", "failed"):
        return False
    failure_code = None
    if update_.status == "failed":
        failure_code = whatsapp.classify(update_.error_code).code
    db.add(
        MessageStatusEvent(
            message_id=message.id,
            status=update_.status,
            provider_timestamp=update_.timestamp,
            error_code=str(update_.error_code) if update_.error_code is not None else None,
            error_detail=update_.error_title,
        )
    )
    current = _STATUS_RANK.get(message.status, -1)
    if update_.status == "failed":
        if message.status != "failed" and current < _STATUS_RANK["delivered"]:
            message.status, message.failure_code = "failed", failure_code
            message.failure_detail = update_.error_title
    elif message.status != "failed" and _STATUS_RANK[update_.status] > current:
        message.status = update_.status
    stamp = {"sent": "sent_at", "delivered": "delivered_at", "read": "read_at"}.get(update_.status)
    if stamp and getattr(message, stamp) is None:
        setattr(message, stamp, update_.timestamp)
    db.execute(update(Conversation).where(Conversation.id == message.conversation_id).values(updated_at=func.now()))
    db.flush()
    return True


def process_whatsapp(db: Session, event: integrations.WebhookEvent) -> str:
    """Webhook processor for WhatsApp: messages, delivery statuses and template status changes."""
    parsed = whatsapp.parse_webhook(event.payload)
    applied = 0
    accounts: dict[str, ChannelAccount | None] = {}

    def account_for(phone_number_id: str) -> ChannelAccount | None:
        if phone_number_id not in accounts:
            accounts[phone_number_id] = channels.whatsapp_account(db, event.connection_id, phone_number_id)
        return accounts[phone_number_id]

    for msg in parsed.messages:
        account = account_for(msg.phone_number_id)
        if account is not None and _store_inbound(db, account, msg):
            applied += 1
    for status in parsed.statuses:
        account = account_for(status.phone_number_id)
        if account is not None and _apply_status(db, account, status):
            applied += 1
    connection_account = channels.channel_account_for(db, event.connection_id)
    for template_update in parsed.templates:
        if connection_account is not None and channels.apply_template_update(db, connection_account, template_update):
            applied += 1
    if applied:
        integrations.mark_success(db, integrations.get_connection(db, event.connection_id))
    return "processed" if applied else "ignored"


# ------------------------------------------------------------------ visibility


def _visibility(db: Session, access: Access) -> ColumnElement[bool]:
    conditions: list[ColumnElement[bool]] = [
        Conversation.account_id.in_(crm.visible_account_ids(db, access)),
    ]
    if access.has_somewhere("inbox.unmatched"):
        conditions.append(Conversation.account_id.is_(None))
    if access.user_id is not None:
        conditions.append(Conversation.assigned_user_id == access.user_id)
    return or_(*conditions)


def _get(db: Session, access: Access, conversation_id: uuid.UUID, lock: bool = False) -> Conversation:
    access.require_somewhere("inbox.read")
    query = select(Conversation).where(Conversation.id == conversation_id, _visibility(db, access))
    conversation = db.scalar(query.with_for_update(of=Conversation) if lock else query)
    if conversation is None:
        raise NotFound("CONVERSATION_NOT_FOUND", "Conversation not found.")
    return conversation


@dataclass(frozen=True)
class ConversationView:
    conversation: Conversation
    channel: str
    channel_name: str
    channel_enabled: bool
    account_name: str | None
    contact_name: str | None
    assigned_name: str | None
    last_message: Message | None
    window_open: bool
    suppressed: bool


def _views(db: Session, rows: list[Conversation]) -> list[ConversationView]:
    if not rows:
        return []
    channel_rows = {c.id: c for c in channels.list_channel_accounts(db)}
    accounts = crm.account_names(db, {r.account_id for r in rows if r.account_id})
    users = identity.user_names(db, {r.assigned_user_id for r in rows if r.assigned_user_id})
    last: dict[uuid.UUID, Message] = {
        m.conversation_id: m
        for m in db.scalars(
            select(Message)
            .where(Message.conversation_id.in_([r.id for r in rows]))
            .distinct(Message.conversation_id)
            .order_by(Message.conversation_id, Message.created_at.desc(), Message.id.desc())
        )
    }
    suppressed = set(
        db.scalars(
            select(SuppressionEntry.value).where(
                SuppressionEntry.kind == "phone",
                SuppressionEntry.lifted_at.is_(None),
                SuppressionEntry.value.in_([r.customer_handle for r in rows]),
            )
        )
    )
    enabled = channels.enabled_numbers(db)
    now = now_utc()
    views = []
    for row in rows:
        account = channel_rows[row.channel_account_id]
        contact = crm.messaging_facts(db, row.contact_id) if row.contact_id else None
        views.append(
            ConversationView(
                row,
                account.channel,
                account.display_name,
                account.status == "active" and account.address in enabled,
                accounts.get(row.account_id) if row.account_id else None,
                contact.name if contact else None,
                users.get(row.assigned_user_id) if row.assigned_user_id else None,
                last.get(row.id),
                row.service_window_expires_at is not None and row.service_window_expires_at > now,
                row.customer_handle in suppressed,
            )
        )
    return views


VIEWS = ("all", "mine", "unassigned", "unmatched")
STATUS_FILTERS = {
    "active": ("open", "pending_customer"),
    "open": ("open",),
    "pending_customer": ("pending_customer",),
    "closed": ("closed",),
}


def list_conversations(
    db: Session,
    access: Access,
    view: str = "all",
    status: str = "active",
    search: str | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> list[ConversationView]:
    access.require_somewhere("inbox.read")
    if view not in VIEWS or status not in STATUS_FILTERS:
        raise ValidationFailed("INVALID_FILTER", "Unknown inbox view or status.")
    query = select(Conversation).where(_visibility(db, access), Conversation.status.in_(STATUS_FILTERS[status]))
    if view == "mine":
        query = query.where(Conversation.assigned_user_id == access.user_id if access.user_id else false())
    elif view == "unassigned":
        query = query.where(Conversation.assigned_user_id.is_(None))
    elif view == "unmatched":
        access.require_somewhere("inbox.unmatched")
        query = query.where(Conversation.account_id.is_(None))
    if search and search.strip():
        term = f"%{search.strip().replace('%', '').replace('_', '')}%"
        query = query.where(or_(Conversation.customer_handle.ilike(term), Conversation.customer_name.ilike(term)))
    if before is not None:
        query = query.where(Conversation.last_activity_at < before)
    rows = list(db.scalars(query.order_by(Conversation.last_activity_at.desc()).limit(min(max(limit, 1), 100))))
    return _views(db, rows)


def view_conversation(db: Session, access: Access, conversation_id: uuid.UUID) -> ConversationView:
    return _views(db, [_get(db, access, conversation_id)])[0]


def list_messages(
    db: Session, access: Access, conversation_id: uuid.UUID, before: datetime | None = None, limit: int = 100
) -> list[Message]:
    conversation = _get(db, access, conversation_id)
    query = select(Message).where(Message.conversation_id == conversation.id)
    if before is not None:
        query = query.where(Message.created_at < before)
    order = (Message.created_at.desc(), Message.provider_timestamp.desc().nulls_last(), Message.id.desc())
    rows = list(db.scalars(query.order_by(*order).limit(min(limit, 200))))
    return list(reversed(rows))


def sender_names(db: Session, messages: list[Message]) -> dict[uuid.UUID, str]:
    principals = {m.sender_principal_id for m in messages if m.sender_principal_id}
    return identity.principal_names(db, principals)


def changes_since(db: Session, access: Access, since: datetime, limit: int = 200) -> list[tuple[uuid.UUID, datetime]]:
    """Visible conversations changed after ``since`` (live updates)."""
    access.require_somewhere("inbox.read")
    rows = db.execute(
        select(Conversation.id, Conversation.updated_at)
        .where(_visibility(db, access), Conversation.updated_at > since)
        .order_by(Conversation.updated_at)
        .limit(limit)
    )
    return [(r.id, r.updated_at) for r in rows]


def unread_total(db: Session, access: Access) -> int:
    access.require_somewhere("inbox.read")
    mine = Conversation.assigned_user_id == access.user_id if access.user_id else false()
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Conversation.unread_count), 0)).where(
                _visibility(db, access),
                Conversation.status != "closed",
                or_(mine, Conversation.assigned_user_id.is_(None)),
            )
        )
        or 0
    )


# ------------------------------------------------------------------ conversation actions


def mark_read(db: Session, actor: Actor, access: Access, conversation_id: uuid.UUID) -> Conversation:
    conversation = _get(db, access, conversation_id, lock=True)
    if conversation.unread_count:
        conversation.unread_count = 0
        db.flush()
    return conversation


def assign(
    db: Session, actor: Actor, access: Access, conversation_id: uuid.UUID, user_id: uuid.UUID | None
) -> Conversation:
    """Assign to someone (needs inbox.assign), or take an unassigned conversation yourself."""
    conversation = _get(db, access, conversation_id, lock=True)
    taking = user_id is not None and user_id == access.user_id and conversation.assigned_user_id is None
    if not taking:
        access.require_somewhere("inbox.assign")
    if user_id is not None and not identity.user_can(db, user_id, "inbox.read"):
        raise ValidationFailed("INVALID_ASSIGNEE", "Assign to an active team member who can use the inbox.")
    before = conversation.assigned_user_id
    if before == user_id:
        return conversation
    conversation.assigned_user_id = user_id
    db.flush()
    audit.record(
        db,
        actor,
        "conversation_assigned",
        "conversation",
        conversation.id,
        {"assigned_user_id": [before, user_id]},
    )
    events.emit(
        db,
        actor,
        "conversation.assigned",
        "conversation",
        conversation.id,
        {"assigned_user_id": user_id},
        conversation.account_id,
    )
    return conversation


def set_status(db: Session, actor: Actor, access: Access, conversation_id: uuid.UUID, status: str) -> Conversation:
    if status not in ("open", "closed"):
        raise ValidationFailed("INVALID_STATUS", "A conversation can be closed or reopened.")
    access.require_somewhere("messaging.send")
    conversation = _get(db, access, conversation_id, lock=True)
    if conversation.status == status:
        return conversation
    before = conversation.status
    conversation.status = status
    if status == "closed":
        conversation.unread_count = 0
    db.flush()
    audit.record(
        db, actor, "conversation_status_changed", "conversation", conversation.id, {"status": [before, status]}
    )
    return conversation


def link_customer(
    db: Session,
    actor: Actor,
    access: Access,
    conversation_id: uuid.UUID,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    save_number: bool,
) -> Conversation:
    """Link a conversation to a household the user can see; optionally save the number on the contact."""
    conversation = _get(db, access, conversation_id, lock=True)
    if conversation.account_id is None:
        access.require_somewhere("inbox.unmatched")
    else:
        access.require_somewhere("inbox.assign")
    if not crm.is_visible(db, access, account_id):
        raise NotFound("ACCOUNT_NOT_FOUND", "Account not found.")
    if contact_id is not None:
        facts = crm.messaging_facts(db, contact_id)
        if facts is None or facts.account_id != account_id:
            raise ValidationFailed("INVALID_CONTACT", "The contact does not belong to this household.")
    elif save_number:
        raise ValidationFailed("CONTACT_REQUIRED", "Choose the contact the number belongs to.")
    before = conversation.account_id
    conversation.account_id, conversation.contact_id = account_id, contact_id
    if conversation.assigned_user_id is None:
        conversation.assigned_user_id = crm.account_for_system(db, account_id).owner_user_id
    if save_number and contact_id is not None:
        kind = "whatsapp" if _channel_of(db, conversation) == "whatsapp" else "email"
        if crm.contact_with_point(db, account_id, kind, conversation.customer_handle) is None:
            crm.add_contact_point(db, actor, access, contact_id, kind, conversation.customer_handle)
    db.flush()
    audit.record(
        db,
        actor,
        "conversation_linked",
        "conversation",
        conversation.id,
        {"account_id": [before, account_id], "contact_id": contact_id},
    )
    events.emit(
        db, actor, "conversation.linked", "conversation", conversation.id, {"contact_id": contact_id}, account_id
    )
    return conversation


def _channel_of(db: Session, conversation: Conversation) -> str:
    account = db.get(ChannelAccount, conversation.channel_account_id)
    return account.channel if account else "whatsapp"


def create_lead(
    db: Session,
    actor: Actor,
    access: Access,
    conversation_id: uuid.UUID,
    guardian_first_name: str | None,
    guardian_last_name: str | None,
    country: str | None,
    student_first_name: str | None,
) -> leads.IntakeResult:
    """Turn an unmatched conversation into a lead (lead intake rules apply) and link it."""
    access.require_somewhere("leads.create")
    conversation = _get(db, access, conversation_id, lock=True)
    access.require_somewhere("inbox.unmatched")
    if conversation.account_id is not None:
        raise Conflict("ALREADY_LINKED", "This conversation is already linked to a customer.")
    first = db.scalar(
        select(Message.body_text)
        .where(Message.conversation_id == conversation.id, Message.direction == "inbound")
        .order_by(Message.created_at)
        .limit(1)
    )
    result = leads.intake(
        db,
        actor,
        access,
        leads.LeadInput(
            source_code="whatsapp_inbound",
            guardian_first_name=guardian_first_name or conversation.customer_name,
            guardian_last_name=guardian_last_name,
            phone=conversation.customer_handle,
            country=country,
            student_first_name=student_first_name,
            message=(first or "")[:2000] or None,
            external_id=f"conversation:{conversation.id}",
        ),
        owner_user_id=None,
        owner_explicit=False,
        manual=False,
    )
    lead = result.lead
    if lead.account_id is not None and (result.account_visible or result.created_account):
        conversation.account_id = lead.account_id
        conversation.contact_id = lead.contact_id or crm.contact_with_point(
            db, lead.account_id, "whatsapp", conversation.customer_handle
        )
        if conversation.assigned_user_id is None:
            conversation.assigned_user_id = crm.account_for_system(db, lead.account_id).owner_user_id
    db.flush()
    audit.record(db, actor, "conversation_lead_created", "conversation", conversation.id, {"lead_id": lead.id})
    return result


def add_note(db: Session, actor: Actor, access: Access, conversation_id: uuid.UUID, text: str) -> Message:
    access.require_somewhere("messaging.send")
    conversation = _get(db, access, conversation_id, lock=True)
    body = text.strip()
    if not body or len(body) > MAX_NOTE_LENGTH:
        raise ValidationFailed("INVALID_NOTE", f"A note needs 1 to {MAX_NOTE_LENGTH} characters.")
    note = Message(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="internal",
        sender_type="user",
        sender_principal_id=actor.principal_id,
        content_type="note",
        body_text=body,
        status="recorded",
    )
    db.add(note)
    conversation.last_activity_at = now_utc()
    db.flush()
    return note


# ------------------------------------------------------------------ sending


@dataclass(frozen=True)
class Queued:
    message: Message
    action_id: uuid.UUID | None  # None when the idempotency key matched an earlier send


def _student_rule(db: Session, conversation: Conversation) -> None:
    if conversation.contact_id is None:
        return
    facts = crm.messaging_facts(db, conversation.contact_id)
    if facts is None or facts.role != "student":
        return
    rule = str(settings.get_value(db, "messaging.student_direct_contact"))
    if rule.startswith("enabled_from_age:") and facts.student_birth_year is not None:
        minimum = int(rule.split(":", 1)[1])
        if now_utc().year - facts.student_birth_year - 1 >= minimum:  # youngest possible age
            return
    raise ValidationFailed(
        "STUDENT_DIRECT_CONTACT_OFF",
        "This contact is a student. Students are not messaged directly (setting messaging.student_direct_contact).",
    )


def _channel_checks(db: Session, conversation: Conversation) -> ChannelAccount:
    account = db.get(ChannelAccount, conversation.channel_account_id)
    if account is None or account.status != "active":
        raise ValidationFailed("CHANNEL_UNAVAILABLE", "This number is not connected any more.")
    connection = integrations.get_connection(db, account.connection_id)
    if connection.status in ("disconnected", "error"):
        raise ValidationFailed(
            "CHANNEL_UNAVAILABLE",
            "The WhatsApp connection needs an administrator (see Integrations) before messages can be sent.",
        )
    if not channels.is_enabled(db, account):
        raise ValidationFailed(
            "CHANNEL_OFF",
            "This WhatsApp number is not switched on yet (setting channels.whatsapp.numbers, question Q-COM-01).",
        )
    if is_suppressed(db, "phone", conversation.customer_handle):
        raise ValidationFailed(
            "RECIPIENT_SUPPRESSED",
            "Messages to this number are blocked (the customer opted out or a manager blocked it).",
        )
    _student_rule(db, conversation)
    return account


def _existing(db: Session, conversation: Conversation, key: str | None) -> Message | None:
    if not key:
        return None
    message = db.scalar(select(Message).where(Message.idempotency_key == key))
    if message is not None and message.conversation_id != conversation.id:
        raise Conflict("IDEMPOTENCY_KEY_REUSED", "This idempotency key was used for another conversation.")
    return message


def _queue(
    db: Session, actor: Actor, conversation: Conversation, message: Message, template: MessageTemplate | None
) -> Queued:
    db.add(message)
    now = now_utc()
    conversation.last_outbound_at = conversation.last_activity_at = now
    conversation.unread_count = 0
    conversation.status = "pending_customer"
    if conversation.assigned_user_id is None and actor.user_id is not None:
        conversation.assigned_user_id = actor.user_id
    db.flush()
    action = events.schedule(db, actor, SEND_ACTION, {"message_id": message.id}, now, dedupe_key=f"send:{message.id}")
    audit.record(
        db,
        actor,
        "message_queued",
        "message",
        message.id,
        {
            "conversation_id": conversation.id,
            "content_type": message.content_type,
            "template": f"{template.name}/{template.language}" if template else None,
        },
    )
    return Queued(message, action.id)


def send_text(
    db: Session, actor: Actor, access: Access, conversation_id: uuid.UUID, body: str, idempotency_key: str | None
) -> Queued:
    access.require_somewhere("messaging.send")
    conversation = _get(db, access, conversation_id, lock=True)
    existing = _existing(db, conversation, idempotency_key)
    if existing is not None:
        return Queued(existing, None)
    text = body.strip()
    if not text or len(text) > whatsapp.MAX_TEXT_LENGTH:
        raise ValidationFailed("INVALID_MESSAGE", f"A message needs 1 to {whatsapp.MAX_TEXT_LENGTH} characters.")
    _channel_checks(db, conversation)
    window = conversation.service_window_expires_at
    if window is None or window <= now_utc():
        raise ValidationFailed(
            "WINDOW_CLOSED",
            "The customer last wrote more than 24 hours ago, so WhatsApp only allows an approved template.",
        )
    message = Message(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="user" if actor.kind == "user" else "agent",
        sender_principal_id=actor.principal_id,
        content_type="text",
        body_text=text,
        status="queued",
        idempotency_key=idempotency_key,
    )
    return _queue(db, actor, conversation, message, None)


def consent_purpose(template: MessageTemplate) -> str:
    return "marketing_whatsapp" if template.category == "marketing" else "service_messages"


def send_template(
    db: Session,
    actor: Actor,
    access: Access,
    conversation_id: uuid.UUID,
    template_id: uuid.UUID,
    variables: list[str],
    idempotency_key: str | None,
) -> Queued:
    access.require_somewhere("messaging.send")
    conversation = _get(db, access, conversation_id, lock=True)
    existing = _existing(db, conversation, idempotency_key)
    if existing is not None:
        return Queued(existing, None)
    account = _channel_checks(db, conversation)
    template = channels.get_template(db, template_id)
    if template.channel_account_id != account.id:
        raise ValidationFailed("TEMPLATE_OTHER_NUMBER", "This template belongs to another WhatsApp number.")
    problem = channels.template_usable(template)
    if problem:
        raise ValidationFailed("TEMPLATE_NOT_USABLE", problem)
    values = [v.strip() for v in variables]
    if len(values) != template.variable_count or any(
        not v or len(v) > MAX_TEMPLATE_VARIABLE_LENGTH or "\n" in v for v in values
    ):
        raise ValidationFailed(
            "TEMPLATE_VARIABLES",
            f"Fill all {template.variable_count} variables (one line each, up to {MAX_TEMPLATE_VARIABLE_LENGTH} "
            "characters).",
        )
    purpose = consent_purpose(template)
    if conversation.contact_id is None:
        raise ValidationFailed(
            "CONSENT_UNKNOWN", "Link this conversation to a customer first: templates need the customer's consent."
        )
    if crm.latest_consent_status(db, conversation.contact_id, purpose) != "granted":
        label = "WhatsApp marketing" if purpose == "marketing_whatsapp" else "service messages"
        raise ValidationFailed("CONSENT_REQUIRED", f"The customer has not given consent to {label}.", purpose=purpose)
    message = Message(
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="user" if actor.kind == "user" else "agent",
        sender_principal_id=actor.principal_id,
        content_type="template",
        body_text=whatsapp.render_template(template.body, values),
        template_id=template.id,
        template_variables=values,
        status="queued",
        idempotency_key=idempotency_key,
    )
    return _queue(db, actor, conversation, message, template)


def _fail(db: Session, message: Message, code: str, detail: str) -> None:
    message.status, message.failure_code, message.failure_detail = "failed", code, detail[:500]
    db.execute(update(Conversation).where(Conversation.id == message.conversation_id).values(updated_at=func.now()))
    db.flush()


def _send_action(db: Session, action: events.Action) -> None:
    message = db.scalar(
        select(Message).where(Message.id == uuid.UUID(str(action.payload["message_id"]))).with_for_update()
    )
    if message is None or message.status != "queued":
        return
    conversation = db.get(Conversation, message.conversation_id)
    account = db.get(ChannelAccount, message.channel_account_id)
    if conversation is None or account is None:
        return
    if is_suppressed(db, "phone", conversation.customer_handle):
        _fail(db, message, "RECIPIENT_SUPPRESSED", "The number was blocked before the message was sent.")
        return
    window = conversation.service_window_expires_at
    if message.content_type == "text" and (window is None or window <= now_utc()):
        _fail(db, message, "WINDOW_CLOSED", "The 24-hour window closed before the message was sent.")
        return
    connection = integrations.get_connection(db, account.connection_id)
    try:
        cfg = channels.graph_config(db, connection)
        if message.content_type == "template" and message.template_id is not None:
            template = channels.get_template(db, message.template_id)
            provider_id = whatsapp.send_template(
                cfg,
                account.external_id,
                conversation.customer_handle,
                template.name,
                template.language,
                list(message.template_variables or []),
            )
        else:
            provider_id = whatsapp.send_text(
                cfg, account.external_id, conversation.customer_handle, message.body_text or ""
            )
    except whatsapp.WhatsAppError as exc:
        if exc.kind.retryable:
            raise events.RetryLater(exc.kind.code, exc.retry_after) from exc
        if exc.kind.connection_problem:
            integrations.mark_error(db, connection, f"{exc.kind.code}: {exc.detail}")
        _fail(db, message, exc.kind.code, exc.detail)
        return
    message.provider_message_id, message.status = provider_id, "sending"
    integrations.mark_success(db, connection)
    db.execute(update(Conversation).where(Conversation.id == conversation.id).values(updated_at=func.now()))
    db.flush()


def _send_gave_up(db: Session, action: events.Action) -> None:
    message = db.get(Message, uuid.UUID(str(action.payload["message_id"])))
    if message is not None and message.status == "queued":
        _fail(db, message, "SEND_GAVE_UP", f"Not sent after {action.attempts} attempts: {action.last_error or ''}")


def retry_failed(db: Session, actor: Actor, access: Access, message_id: uuid.UUID) -> Queued:
    """Send a failed message again as a new message (the failed one stays in the history)."""
    message = db.get(Message, message_id)
    if message is None or message.direction != "outbound":
        raise NotFound("MESSAGE_NOT_FOUND", "Message not found.")
    if message.status != "failed":
        raise ValidationFailed("NOT_FAILED", "Only failed messages can be sent again.")
    if message.content_type == "template" and message.template_id is not None:
        return send_template(
            db,
            actor,
            access,
            message.conversation_id,
            message.template_id,
            list(message.template_variables or []),
            None,
        )
    return send_text(db, actor, access, message.conversation_id, message.body_text or "", None)


def templates_for(db: Session, access: Access, conversation_id: uuid.UUID) -> list[tuple[MessageTemplate, str | None]]:
    """Templates of the conversation's number, each with the reason it cannot be sent now (or None)."""
    conversation = _get(db, access, conversation_id)
    contact_consents: dict[str, str | None] = {}
    rows = []
    for template in channels.list_templates(db, conversation.channel_account_id):
        if template.provider_status == "disabled" or template.internal_status == "retired":
            continue
        problem = channels.template_usable(template)
        if problem is None:
            purpose = consent_purpose(template)
            if conversation.contact_id is None:
                problem = "Link the conversation to a customer first."
            else:
                if purpose not in contact_consents:
                    contact_consents[purpose] = crm.latest_consent_status(db, conversation.contact_id, purpose)
                if contact_consents[purpose] != "granted":
                    problem = (
                        "No consent to WhatsApp marketing."
                        if purpose == "marketing_whatsapp"
                        else ("No consent to service messages.")
                    )
        rows.append((template, problem))
    return rows


def conversations_for_account(db: Session, access: Access, account_id: uuid.UUID) -> list[ConversationView]:
    """Conversations linked to a household (customer page)."""
    access.require_somewhere("inbox.read")
    if not crm.is_visible(db, access, account_id):
        raise NotFound("ACCOUNT_NOT_FOUND", "Account not found.")
    rows = list(
        db.scalars(
            select(Conversation)
            .where(and_(Conversation.account_id == account_id))
            .order_by(Conversation.last_activity_at.desc())
            .limit(20)
        )
    )
    return _views(db, rows)
