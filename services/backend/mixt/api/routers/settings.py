"""Configurable settings and the 'Outstanding decisions' view (ADR-11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, require
from mixt.core.db import get_session
from mixt.modules.settings import service as settings
from mixt.modules.settings.service import EffectiveSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingOut(BaseModel):
    key: str
    area: str
    description: str
    value: Any
    status: str
    decision_ref: str | None
    open_question: str | None
    source: str
    scope_type: str
    scope_id: str | None
    version: int | None
    allowed_scopes: list[str]
    change_permission: str
    requires_dual_approval: bool
    value_schema: dict[str, Any]


class SettingDetailOut(SettingOut):
    scoped_overrides: list[dict[str, Any]]


class SettingChangeIn(BaseModel):
    value: Any
    status: str
    decision_ref: str | None = None
    scope_type: str = "global"
    scope_id: str | None = None
    expected_version: int | None = None


def _out(s: EffectiveSetting) -> SettingOut:
    d = s.definition
    return SettingOut(
        key=d.key,
        area=d.area,
        description=d.description,
        value=s.value,
        status=s.status,
        decision_ref=s.decision_ref,
        open_question=d.open_question,
        source=s.source,
        scope_type=s.scope_type,
        scope_id=s.scope_id,
        version=s.version,
        allowed_scopes=list(d.scopes),
        change_permission=d.change_permission,
        requires_dual_approval=d.requires_dual_approval,
        value_schema=d.schema,
    )


@router.get("", response_model=list[SettingOut])
def list_settings(
    _: AuthContext = Depends(require("settings.read")), db: Session = Depends(get_session, scope="function")
) -> list[SettingOut]:
    return [_out(s) for s in settings.list_effective(db)]


@router.get("/outstanding", response_model=list[SettingOut])
def outstanding(
    _: AuthContext = Depends(require("settings.read")), db: Session = Depends(get_session, scope="function")
) -> list[SettingOut]:
    return [_out(s) for s in settings.outstanding(db)]


@router.get("/{key}", response_model=SettingDetailOut)
def get_setting(
    key: str, _: AuthContext = Depends(require("settings.read")), db: Session = Depends(get_session, scope="function")
) -> SettingDetailOut:
    base = _out(settings.get(db, key))
    overrides = [
        {
            "scope_type": o.scope_type,
            "scope_id": o.scope_id,
            "value": o.value["v"],
            "status": o.status,
            "decision_ref": o.decision_ref,
            "version": o.version,
        }
        for o in settings.list_scoped_overrides(db, key)
    ]
    return SettingDetailOut(**base.model_dump(), scoped_overrides=overrides)


@router.put("/{key}", response_model=SettingOut)
def change_setting(
    key: str,
    body: SettingChangeIn,
    auth: AuthContext = Depends(require("settings.read")),
    db: Session = Depends(get_session, scope="function"),
) -> SettingOut:
    result = settings.change(
        db,
        auth.actor,
        auth.access,
        key,
        body.value,
        body.status,
        body.decision_ref,
        body.scope_type,
        body.scope_id,
        body.expected_version,
    )
    return _out(result)
