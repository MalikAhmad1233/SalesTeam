"""Messaging tables (docs/02 §6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk


class ChannelAccount(Base):
    """One number or mailbox Mixt talks from, bound to an integration connection."""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("channel", "external_id"),
        CheckConstraint("channel IN ('whatsapp','email','web_form')", name="channel"),
        CheckConstraint("status IN ('active','disabled')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    channel: Mapped[str] = mapped_column(String(16))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    external_id: Mapped[str] = mapped_column(Text)  # WhatsApp phone_number_id / mailbox address
    display_name: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)  # the number or address customers see (E.164 / email)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    created_at: Mapped[datetime] = created_at_col()


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel_account_id", "customer_handle"),
        CheckConstraint("status IN ('open','pending_customer','closed')", name="status"),
        CheckConstraint("handling_mode IN ('human_only','ai_draft')", name="handling_mode"),
        Index("ix_conversations_last_activity", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    channel_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_accounts.id"))
    customer_handle: Mapped[str] = mapped_column(Text)  # E.164 phone (WhatsApp) or email address
    customer_name: Mapped[str | None] = mapped_column(Text)  # as the channel reports it (profile name)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id"))
    subject: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), server_default=text("'open'"))
    handling_mode: Mapped[str] = mapped_column(String(16), server_default=text("'human_only'"))
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    last_inbound_at: Mapped[datetime | None]
    last_outbound_at: Mapped[datetime | None]
    last_activity_at: Mapped[datetime] = created_at_col()
    service_window_expires_at: Mapped[datetime | None]  # WhatsApp customer-service window
    unread_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()  # also touched when a message's status changes (live updates)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("channel_account_id", "provider_message_id"),
        CheckConstraint("direction IN ('inbound','outbound','internal')", name="direction"),
        CheckConstraint("sender_type IN ('customer','user','agent','system')", name="sender_type"),
        CheckConstraint(
            "content_type IN ('text','template','media','interactive','email','note')", name="content_type"
        ),
        CheckConstraint(
            "status IN ('received','queued','sending','sent','delivered','read','failed','recorded')", name="status"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    channel_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_accounts.id"))
    direction: Mapped[str] = mapped_column(String(16))
    sender_type: Mapped[str] = mapped_column(String(16))
    sender_principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    content_type: Mapped[str] = mapped_column(String(16))
    body_text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # type, provider media id, mime type, caption
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("message_templates.id"))
    template_variables: Mapped[list[str] | None] = mapped_column(JSONB)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    provider_timestamp: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_col()


class MessageStatusEvent(Base):
    __tablename__ = "message_status_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    provider_timestamp: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = created_at_col()


class MessageTemplate(Base):
    """A WhatsApp template as approved by Meta, which Mixt must also approve before staff can use it."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("channel_account_id", "name", "language"),
        CheckConstraint("category IN ('marketing','utility','authentication')", name="category"),
        CheckConstraint(
            "provider_status IN ('pending','approved','rejected','paused','disabled')", name="provider_status"
        ),
        CheckConstraint("internal_status IN ('not_reviewed','approved','retired')", name="internal_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    channel_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_accounts.id"))
    name: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # as Meta returns them
    variable_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    unsupported_reason: Mapped[str | None] = mapped_column(Text)  # set when Mixt cannot fill this template yet
    provider_template_id: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str] = mapped_column(String(16))
    internal_status: Mapped[str] = mapped_column(String(16), server_default=text("'not_reviewed'"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None]
    synced_at: Mapped[datetime] = created_at_col()


class SuppressionEntry(Base):
    """Never message this number or address (opt-out, bounce, complaint, legal, manual).

    Entries are lifted, not deleted, so the history of who stopped messages and who allowed them
    again is kept. Only one active entry per number or address.
    """

    __tablename__ = "suppression_list"
    __table_args__ = (
        CheckConstraint("kind IN ('phone','email')", name="kind"),
        CheckConstraint("reason IN ('opt_out','bounce','complaint','legal','manual')", name="reason"),
        CheckConstraint("(lifted_at IS NULL) = (lift_reason IS NULL)", name="lift_pair"),
        Index("uq_suppression_list_active", "kind", "value", unique=True, postgresql_where=text("lifted_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(8))
    value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = created_at_col()
    lifted_at: Mapped[datetime | None]
    lifted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    lift_reason: Mapped[str | None] = mapped_column(Text)
