"""Integration tables (docs/02 §15). Credentials are encrypted and never leave the integrations module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk

PROVIDERS = ("meta_whatsapp_cloud", "gmail", "microsoft_graph", "website_forms")


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(f"provider IN ({', '.join(repr(p) for p in PROVIDERS)})", name="provider"),
        CheckConstraint("status IN ('pending','connected','error','disconnected')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)  # non-secret settings only
    connected_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    connected_at: Mapped[datetime] = created_at_col()
    last_success_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    rejected_webhooks: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_rejected_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = updated_at_col()


class IntegrationCredential(Base):
    """A secret (token, app secret, verify token). Stored encrypted; never returned by any API."""

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("connection_id", "kind"),
        CheckConstraint(
            "kind IN ('access_token','refresh_token','app_secret','verify_token','client_secret','api_key')",
            name="kind",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(Text)
    rotated_at: Mapped[datetime] = created_at_col()


class InboundWebhookEvent(Base):
    """Every verified webhook, stored before it is processed, so nothing is lost when processing fails."""

    __tablename__ = "inbound_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id"),
        CheckConstraint("status IN ('received','processed','ignored','failed')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_event_id: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'received'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = created_at_col()
    processed_at: Mapped[datetime | None]
