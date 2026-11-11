"""Phase 3b: email over IMAP/SMTP (BD-034)

Mixt uses neither Google Workspace nor Microsoft 365, so the provider list drops the Gmail and
Microsoft Graph adapters and gains a generic IMAP/SMTP mailbox. Adds the mailbox password secret,
email headers on messages, mailbox polling state, and the consent source for an opt-out by email.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10 19:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDERS_NEW = "provider IN ('meta_whatsapp_cloud', 'imap_smtp', 'website_forms')"
_PROVIDERS_OLD = "provider IN ('meta_whatsapp_cloud', 'gmail', 'microsoft_graph', 'website_forms')"
_KINDS_NEW = "kind IN ('access_token','refresh_token','app_secret','verify_token','client_secret','api_key','password')"
_KINDS_OLD = "kind IN ('access_token','refresh_token','app_secret','verify_token','client_secret','api_key')"
_SOURCES_NEW = (
    "source IN ('web_form','lead_ad_form','whatsapp_keyword','email_reply','email_link','staff_logged','import')"
)
_SOURCES_OLD = "source IN ('web_form','lead_ad_form','whatsapp_keyword','email_link','staff_logged','import')"

_GUARD = """
CREATE OR REPLACE FUNCTION messages_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'messages are never deleted' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.conversation_id <> OLD.conversation_id OR NEW.channel_account_id <> OLD.channel_account_id
    OR NEW.direction <> OLD.direction OR NEW.sender_type <> OLD.sender_type
    OR NEW.sender_principal_id IS DISTINCT FROM OLD.sender_principal_id OR NEW.content_type <> OLD.content_type
    OR NEW.body_text IS DISTINCT FROM OLD.body_text OR NEW.template_id IS DISTINCT FROM OLD.template_id
    OR NEW.template_variables IS DISTINCT FROM OLD.template_variables OR NEW.created_at <> OLD.created_at
    {extra} THEN
    RAISE EXCEPTION 'message content never changes' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    _replace_check("integration_connections", "provider", _PROVIDERS_NEW)
    _replace_check("integration_credentials", "kind", _KINDS_NEW)
    _replace_check("consents", "source", _SOURCES_NEW)
    op.add_column("channel_accounts", sa.Column("sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("email_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute(_GUARD.replace("{extra}", "OR NEW.email_meta IS DISTINCT FROM OLD.email_meta"))


def downgrade() -> None:
    op.execute(_GUARD.replace("{extra}", ""))
    op.drop_column("messages", "email_meta")
    op.drop_column("channel_accounts", "sync_state")
    _replace_check("consents", "source", _SOURCES_OLD)
    _replace_check("integration_credentials", "kind", _KINDS_OLD)
    _replace_check("integration_connections", "provider", _PROVIDERS_OLD)
