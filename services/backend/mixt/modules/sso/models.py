"""Links between staff accounts and single sign-on identities (IN-23)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, uuid_pk


class UserIdentity(Base):
    """One provider account per staff user and provider. The provider's stable subject is the key:
    after the first link, sign-in never depends on the (changeable) email address again."""

    __tablename__ = "user_identities"
    __table_args__ = (
        CheckConstraint("provider IN ('google','microsoft')", name="provider"),
        UniqueConstraint("provider", "subject"),
        UniqueConstraint("user_id", "provider"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(Text)
    email_at_link: Mapped[str] = mapped_column(CITEXT)
    created_at: Mapped[datetime] = created_at_col()
    last_login_at: Mapped[datetime | None]
