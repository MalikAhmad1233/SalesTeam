"""Stored values for the configurable settings register (ADR-11).

Setting *definitions* (schema, safe default, permission) live in code, in ``registry.py``, next to
the code that interprets them. This table only holds values that differ from the registry default
or that Mixt has confirmed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, updated_at_col, uuid_pk


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("key", "scope_type", "scope_id", postgresql_nulls_not_distinct=True, name="uq_setting_scope"),
        CheckConstraint("status IN ('safe_default','confirmed')", name="status"),
        CheckConstraint("status <> 'confirmed' OR decision_ref ~ '^BD-[0-9]{3}$'", name="confirmed_needs_decision"),
        CheckConstraint(
            "scope_type IN ('global','market','price_book','price_book_version','channel','agent','role','curriculum',"
            "'pipeline','stage','data_type','deployment','action')",
            name="scope_type",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[str | None] = mapped_column(Text)
    value: Mapped[dict[str, Any]]  # stored as {"v": <value>} so scalars are valid JSONB documents
    status: Mapped[str] = mapped_column(String(16))
    decision_ref: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}
