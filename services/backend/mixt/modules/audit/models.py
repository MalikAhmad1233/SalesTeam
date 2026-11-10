"""Append-only, hash-chained audit log (DB-09). Hashes are computed by a database trigger."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    chain_seq: Mapped[int] = mapped_column(BigInteger, unique=True)  # set by trigger
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    actor_principal_id: Mapped[uuid.UUID]
    actor_kind: Mapped[str] = mapped_column(String(16))
    approved_by_user_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    row_hash: Mapped[bytes] = mapped_column(LargeBinary)  # set by trigger


Index("ix_audit_log_entity", AuditLog.entity_type, AuditLog.entity_id)
Index("ix_audit_log_actor", AuditLog.actor_principal_id, AuditLog.occurred_at)
