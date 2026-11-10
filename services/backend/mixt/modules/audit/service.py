"""Audit trail: record changes and verify the hash chain.

Every service that changes data calls :func:`record` inside the same transaction as the change,
so a change and its audit entry are committed (or rolled back) together.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.modules.audit.models import AuditLog

MASK = "[masked]"


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return MASK
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


jsonable = _jsonable  # public alias for other modules


def diff(before: dict[str, Any], after: dict[str, Any], sensitive: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Return {field: {"from": old, "to": new}} for changed fields; sensitive values are masked."""
    changes: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            if key in sensitive:
                changes[key] = {"from": MASK if old is not None else None, "to": MASK if new is not None else None}
            else:
                changes[key] = {"from": _jsonable(old), "to": _jsonable(new)}
    return changes


def record(
    session: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None,
    changes: dict[str, Any] | None = None,
    approved_by_user_id: uuid.UUID | None = None,
) -> None:
    session.execute(
        insert(AuditLog).values(
            actor_principal_id=actor.principal_id,
            actor_kind=actor.kind,
            approved_by_user_id=approved_by_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            changes=_jsonable(changes) if changes is not None else None,
            ip=actor.ip,
            user_agent=actor.user_agent,
            correlation_id=actor.correlation_id,
        )
    )


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    rows_checked: int
    first_broken_chain_seq: int | None
    reason: str | None


_VERIFY_SQL = text(
    """
    SELECT chain_seq,
           prev_hash IS NOT DISTINCT FROM lag(row_hash) OVER (ORDER BY chain_seq) AS prev_ok,
           row_hash = audit_log_row_digest(prev_hash, a) AS hash_ok,
           chain_seq = row_number() OVER (ORDER BY chain_seq) AS seq_ok
    FROM audit_log a
    ORDER BY chain_seq
    """
)


def verify_chain(session: Session) -> ChainVerification:
    """Recompute every hash. Detects edited rows, removed rows (sequence gaps) and re-ordering."""
    count = 0
    for row in session.execute(_VERIFY_SQL):
        count += 1
        if not row.seq_ok:
            return ChainVerification(False, count, row.chain_seq, "sequence gap: a row was removed")
        if not row.prev_ok:
            return ChainVerification(False, count, row.chain_seq, "previous-hash link broken")
        if not row.hash_ok:
            return ChainVerification(False, count, row.chain_seq, "row content does not match its hash")
    return ChainVerification(True, count, None, None)


def list_entries(
    session: Session,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 200))
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if before_id:
        query = query.where(AuditLog.id < before_id)
    return list(session.scalars(query))
