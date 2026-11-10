"""Phase 3a: integrations, channel accounts, conversations, messages, templates, suppression list

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10 18:01:15
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NS = uuid.UUID("6f1d3a52-2c3e-4b8e-9a51-6d1f2b7c9e10")


def _sid(kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


NEW_PERMISSIONS = {
    "integrations.manage": "Connect, check and disconnect integrations, rotate their secrets, replay failed webhooks",
    "inbox.read": "Read conversations of customers the user can see, and conversations assigned to them",
    "inbox.unmatched": "Read conversations not yet linked to a customer, link them or create a lead from them",
    "inbox.assign": "Assign conversations to any team member",
    "messaging.send": "Reply to customers and send approved templates (channel rules, consent and opt-outs apply)",
    "messaging.templates.approve": "Approve or retire message templates for use by staff",
    "messaging.suppression.manage": "Block a number or address, or allow messages to it again (with a reason)",
}
_INBOX = ["inbox.read", "inbox.unmatched", "inbox.assign", "messaging.send", "messaging.suppression.manage"]
NEW_GRANTS = {
    "owner": list(NEW_PERMISSIONS),
    # Admins create sales staff and can only grant what they hold.
    "admin": ["integrations.manage", "messaging.templates.approve", *_INBOX],
    "sales_manager": _INBOX,
    "sales_rep": ["inbox.read", "messaging.send"],
}

TRIGGERS = """
CREATE TRIGGER trg_message_status_events_append_only BEFORE UPDATE OR DELETE ON message_status_events
  FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_message_status_events_no_truncate BEFORE TRUNCATE ON message_status_events
  FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();

-- A message is a record of what was said: it is never deleted and its content never changes.
CREATE FUNCTION messages_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'messages are never deleted' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.conversation_id <> OLD.conversation_id OR NEW.channel_account_id <> OLD.channel_account_id
    OR NEW.direction <> OLD.direction OR NEW.sender_type <> OLD.sender_type
    OR NEW.sender_principal_id IS DISTINCT FROM OLD.sender_principal_id OR NEW.content_type <> OLD.content_type
    OR NEW.body_text IS DISTINCT FROM OLD.body_text OR NEW.template_id IS DISTINCT FROM OLD.template_id
    OR NEW.template_variables IS DISTINCT FROM OLD.template_variables OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'message content never changes' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_messages_guard BEFORE UPDATE OR DELETE ON messages
  FOR EACH ROW EXECUTE FUNCTION messages_guard();

-- The raw webhook body is evidence of what the provider sent: processing may change its status only.
CREATE FUNCTION inbound_webhook_events_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'webhook events are never deleted' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.provider <> OLD.provider
    OR NEW.external_event_id <> OLD.external_event_id OR NEW.connection_id <> OLD.connection_id
    OR NEW.received_at <> OLD.received_at THEN
    RAISE EXCEPTION 'a received webhook never changes' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_inbound_webhook_events_guard BEFORE UPDATE OR DELETE ON inbound_webhook_events
  FOR EACH ROW EXECUTE FUNCTION inbound_webhook_events_guard();
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_inbound_webhook_events_guard ON inbound_webhook_events;
DROP FUNCTION IF EXISTS inbound_webhook_events_guard();
DROP TRIGGER IF EXISTS trg_messages_guard ON messages;
DROP FUNCTION IF EXISTS messages_guard();
DROP TRIGGER IF EXISTS trg_message_status_events_no_truncate ON message_status_events;
DROP TRIGGER IF EXISTS trg_message_status_events_append_only ON message_status_events;
"""


def _seed() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO permissions (key, description) VALUES (:k, :d)"),
        [{"k": k, "d": d} for k, d in NEW_PERMISSIONS.items()],
    )
    for role, perms in NEW_GRANTS.items():
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:r, :p)"),
            [{"r": _sid("role", role), "p": p} for p in perms],
        )


def _unseed() -> None:
    conn = op.get_bind()
    keys = list(NEW_PERMISSIONS)
    conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_key = ANY(:keys)"), {"keys": keys})
    conn.execute(sa.text("DELETE FROM permissions WHERE key = ANY(:keys)"), {"keys": keys})


def _schema_up() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("connected_by", sa.Uuid(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("rejected_webhooks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "provider IN ('meta_whatsapp_cloud', 'gmail', 'microsoft_graph', 'website_forms')",
            name=op.f("ck_integration_connections_provider"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','connected','error','disconnected')", name=op.f("ck_integration_connections_status")
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"], ["principals.id"], name=op.f("fk_integration_connections_connected_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_connections")),
    )
    op.create_table(
        "suppression_list",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by", sa.Uuid(), nullable=True),
        sa.Column("lift_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('phone','email')", name=op.f("ck_suppression_list_kind")),
        sa.CheckConstraint(
            "reason IN ('opt_out','bounce','complaint','legal','manual')", name=op.f("ck_suppression_list_reason")
        ),
        sa.CheckConstraint("(lifted_at IS NULL) = (lift_reason IS NULL)", name=op.f("ck_suppression_list_lift_pair")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["principals.id"], name=op.f("fk_suppression_list_created_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["lifted_by"], ["principals.id"], name=op.f("fk_suppression_list_lifted_by_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppression_list")),
    )
    op.create_index(
        "uq_suppression_list_active",
        "suppression_list",
        ["kind", "value"],
        unique=True,
        postgresql_where=sa.text("lifted_at IS NULL"),
    )
    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("channel IN ('whatsapp','email','web_form')", name=op.f("ck_channel_accounts_channel")),
        sa.CheckConstraint("status IN ('active','disabled')", name=op.f("ck_channel_accounts_status")),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            name=op.f("fk_channel_accounts_connection_id_integration_connections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_accounts")),
        sa.UniqueConstraint("channel", "external_id", name=op.f("uq_channel_accounts_channel_external_id")),
    )
    op.create_index(op.f("ix_channel_accounts_connection_id"), "channel_accounts", ["connection_id"], unique=False)
    op.create_table(
        "inbound_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_event_id", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'received'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('received','processed','ignored','failed')", name=op.f("ck_inbound_webhook_events_status")
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            name=op.f("fk_inbound_webhook_events_connection_id_integration_connections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_webhook_events")),
        sa.UniqueConstraint(
            "provider", "external_event_id", name=op.f("uq_inbound_webhook_events_provider_external_event_id")
        ),
    )
    op.create_index(
        op.f("ix_inbound_webhook_events_connection_id"), "inbound_webhook_events", ["connection_id"], unique=False
    )
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('access_token','refresh_token','app_secret','verify_token','client_secret','api_key')",
            name=op.f("ck_integration_credentials_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            name=op.f("fk_integration_credentials_connection_id_integration_connections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_credentials")),
        sa.UniqueConstraint("connection_id", "kind", name=op.f("uq_integration_credentials_connection_id_kind")),
    )
    op.create_index(
        op.f("ix_integration_credentials_connection_id"), "integration_credentials", ["connection_id"], unique=False
    )
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("variable_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unsupported_reason", sa.Text(), nullable=True),
        sa.Column("provider_template_id", sa.Text(), nullable=True),
        sa.Column("provider_status", sa.String(length=16), nullable=False),
        sa.Column("internal_status", sa.String(length=16), server_default=sa.text("'not_reviewed'"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('marketing','utility','authentication')", name=op.f("ck_message_templates_category")
        ),
        sa.CheckConstraint(
            "internal_status IN ('not_reviewed','approved','retired')",
            name=op.f("ck_message_templates_internal_status"),
        ),
        sa.CheckConstraint(
            "provider_status IN ('pending','approved','rejected','paused','disabled')",
            name=op.f("ck_message_templates_provider_status"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["principals.id"], name=op.f("fk_message_templates_approved_by_principals")
        ),
        sa.ForeignKeyConstraint(
            ["channel_account_id"],
            ["channel_accounts.id"],
            name=op.f("fk_message_templates_channel_account_id_channel_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_templates")),
        sa.UniqueConstraint(
            "channel_account_id", "name", "language", name=op.f("uq_message_templates_channel_account_id_name_language")
        ),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_account_id", sa.Uuid(), nullable=False),
        sa.Column("customer_handle", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default=sa.text("'open'"), nullable=False),
        sa.Column("handling_mode", sa.String(length=16), server_default=sa.text("'human_only'"), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("service_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unread_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("handling_mode IN ('human_only','ai_draft')", name=op.f("ck_conversations_handling_mode")),
        sa.CheckConstraint("status IN ('open','pending_customer','closed')", name=op.f("ck_conversations_status")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_conversations_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"], ["users.id"], name=op.f("fk_conversations_assigned_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["channel_account_id"],
            ["channel_accounts.id"],
            name=op.f("fk_conversations_channel_account_id_channel_accounts"),
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name=op.f("fk_conversations_contact_id_contacts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "channel_account_id", "customer_handle", name=op.f("uq_conversations_channel_account_id_customer_handle")
        ),
    )
    op.create_index(op.f("ix_conversations_account_id"), "conversations", ["account_id"], unique=False)
    op.create_index(op.f("ix_conversations_assigned_user_id"), "conversations", ["assigned_user_id"], unique=False)
    op.create_index("ix_conversations_last_activity", "conversations", ["last_activity_at"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("channel_account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("sender_principal_id", sa.Uuid(), nullable=True),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("media", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("template_variables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "content_type IN ('text','template','media','interactive','email','note')",
            name=op.f("ck_messages_content_type"),
        ),
        sa.CheckConstraint("direction IN ('inbound','outbound','internal')", name=op.f("ck_messages_direction")),
        sa.CheckConstraint("sender_type IN ('customer','user','agent','system')", name=op.f("ck_messages_sender_type")),
        sa.CheckConstraint(
            "status IN ('received','queued','sending','sent','delivered','read','failed','recorded')",
            name=op.f("ck_messages_status"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_account_id"],
            ["channel_accounts.id"],
            name=op.f("fk_messages_channel_account_id_channel_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name=op.f("fk_messages_conversation_id_conversations")
        ),
        sa.ForeignKeyConstraint(
            ["sender_principal_id"], ["principals.id"], name=op.f("fk_messages_sender_principal_id_principals")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["message_templates.id"], name=op.f("fk_messages_template_id_message_templates")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "channel_account_id", "provider_message_id", name=op.f("uq_messages_channel_account_id_provider_message_id")
        ),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_messages_idempotency_key")),
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], unique=False)
    op.create_table(
        "message_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name=op.f("fk_message_status_events_message_id_messages")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_status_events")),
    )
    op.create_index(op.f("ix_message_status_events_message_id"), "message_status_events", ["message_id"], unique=False)


def _schema_down() -> None:
    op.drop_index(op.f("ix_message_status_events_message_id"), table_name="message_status_events")
    op.drop_table("message_status_events")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_last_activity", table_name="conversations")
    op.drop_index(op.f("ix_conversations_assigned_user_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_account_id"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("message_templates")
    op.drop_index(op.f("ix_integration_credentials_connection_id"), table_name="integration_credentials")
    op.drop_table("integration_credentials")
    op.drop_index(op.f("ix_inbound_webhook_events_connection_id"), table_name="inbound_webhook_events")
    op.drop_table("inbound_webhook_events")
    op.drop_index(op.f("ix_channel_accounts_connection_id"), table_name="channel_accounts")
    op.drop_table("channel_accounts")
    op.drop_index(
        "uq_suppression_list_active", table_name="suppression_list", postgresql_where=sa.text("lifted_at IS NULL")
    )
    op.drop_table("suppression_list")
    op.drop_table("integration_connections")


def upgrade() -> None:
    _schema_up()
    op.execute(TRIGGERS)
    _seed()


def downgrade() -> None:
    _unseed()
    op.execute(DROP_TRIGGERS)
    _schema_down()
