"""Audit log reading and integrity verification."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, require
from mixt.core.db import get_session
from mixt.modules.audit import service as audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chain_seq: int
    occurred_at: datetime
    actor_principal_id: uuid.UUID
    actor_kind: str
    approved_by_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    changes: dict[str, Any] | None
    correlation_id: str | None


class VerificationOut(BaseModel):
    ok: bool
    rows_checked: int
    first_broken_chain_seq: int | None
    reason: str | None


@router.get("", response_model=list[AuditEntryOut])
def list_entries(
    entity_type: str | None = None,
    entity_id: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
    _: AuthContext = Depends(require("audit.read")),
    db: Session = Depends(get_session, scope="function"),
) -> list[AuditEntryOut]:
    return [AuditEntryOut.model_validate(e) for e in audit.list_entries(db, entity_type, entity_id, before_id, limit)]


@router.post("/verify", response_model=VerificationOut)
def verify(
    _: AuthContext = Depends(require("audit.verify")), db: Session = Depends(get_session, scope="function")
) -> VerificationOut:
    result = audit.verify_chain(db)
    return VerificationOut(
        ok=result.ok,
        rows_checked=result.rows_checked,
        first_broken_chain_seq=result.first_broken_chain_seq,
        reason=result.reason,
    )
