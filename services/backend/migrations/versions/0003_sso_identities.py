"""Phase 1d: single sign-on identity links

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email_at_link", postgresql.CITEXT(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('google','microsoft')", name=op.f("ck_user_identities_provider")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_identities_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_user_identities_provider_subject")),
        sa.UniqueConstraint("user_id", "provider", name=op.f("uq_user_identities_user_id_provider")),
    )
    op.create_index(op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_table("user_identities")
