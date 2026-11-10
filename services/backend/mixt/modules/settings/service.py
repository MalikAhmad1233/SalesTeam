"""Read and change configurable settings (ADR-11).

Effective value lookup: exact scope row -> global row -> registry default.
Changes that need dual approval are refused until the approvals module ships (Phase 2).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.settings.models import SystemSetting
from mixt.modules.settings.registry import BY_KEY, DEFINITIONS, SettingDefinition

_DECISION_REF = re.compile(r"^BD-[0-9]{3}$")

# Extra checks owned by other modules (e.g. the pipeline refuses to drop a stage that is in use).
Validator = Callable[[Session, Any], None]
_VALIDATORS: dict[str, Validator] = {}


def register_validator(key: str, validator: Validator) -> None:
    definition(key)
    _VALIDATORS[key] = validator


@dataclass(frozen=True)
class EffectiveSetting:
    definition: SettingDefinition
    value: Any
    status: str
    decision_ref: str | None
    source: str  # 'registry' | 'global' | 'scoped'
    scope_type: str
    scope_id: str | None
    version: int | None


def definition(key: str) -> SettingDefinition:
    try:
        return BY_KEY[key]
    except KeyError as exc:
        raise NotFound("SETTING_NOT_FOUND", f"Unknown setting '{key}'.") from exc


def _row(db: Session, key: str, scope_type: str, scope_id: str | None) -> SystemSetting | None:
    query = select(SystemSetting).where(SystemSetting.key == key, SystemSetting.scope_type == scope_type)
    query = query.where(SystemSetting.scope_id.is_(None) if scope_id is None else SystemSetting.scope_id == scope_id)
    return db.scalar(query)


def get(db: Session, key: str, scope_type: str = "global", scope_id: str | None = None) -> EffectiveSetting:
    d = definition(key)
    if scope_type != "global":
        row = _row(db, key, scope_type, scope_id)
        if row is not None:
            return EffectiveSetting(
                d, row.value["v"], row.status, row.decision_ref, "scoped", scope_type, scope_id, row.version
            )
    row = _row(db, key, "global", None)
    if row is not None:
        return EffectiveSetting(d, row.value["v"], row.status, row.decision_ref, "global", "global", None, row.version)
    return EffectiveSetting(d, d.default, d.status, d.decision_ref, "registry", "global", None, None)


def get_value(db: Session, key: str, scope_type: str = "global", scope_id: str | None = None) -> Any:
    return get(db, key, scope_type, scope_id).value


def list_effective(db: Session) -> list[EffectiveSetting]:
    return [get(db, d.key) for d in DEFINITIONS]


def list_scoped_overrides(db: Session, key: str) -> list[SystemSetting]:
    definition(key)
    return list(
        db.scalars(
            select(SystemSetting)
            .where(SystemSetting.key == key, SystemSetting.scope_type != "global")
            .order_by(SystemSetting.scope_type, SystemSetting.scope_id)
        )
    )


def outstanding(db: Session) -> list[EffectiveSetting]:
    """Settings still on a safe default: the 'Outstanding decisions' view."""
    return [s for s in list_effective(db) if s.status == "safe_default"]


def change(
    db: Session,
    actor: Actor,
    access: Access,
    key: str,
    value: Any,
    status: str,
    decision_ref: str | None,
    scope_type: str = "global",
    scope_id: str | None = None,
    expected_version: int | None = None,
) -> EffectiveSetting:
    d = definition(key)
    access.require(d.change_permission)
    if d.requires_dual_approval:
        raise Conflict(
            "DUAL_APPROVAL_REQUIRED",
            f"'{key}' needs two approvers. The approval workflow arrives with Phase 2; until then this setting "
            "keeps its current value.",
        )
    if scope_type not in d.scopes:
        raise ValidationFailed("INVALID_SCOPE", f"'{key}' cannot be set at scope '{scope_type}'.", allowed=d.scopes)
    if (scope_type == "global") != (scope_id is None):
        raise ValidationFailed("INVALID_SCOPE", "Global settings have no scope id; scoped settings need one.")
    try:
        jsonschema.validate(value, d.schema)
    except jsonschema.ValidationError as exc:
        raise ValidationFailed("INVALID_SETTING_VALUE", f"Invalid value for '{key}': {exc.message}") from exc
    if key in _VALIDATORS:
        _VALIDATORS[key](db, value)
    if status not in ("safe_default", "confirmed"):
        raise ValidationFailed("INVALID_STATUS", "Status must be 'safe_default' or 'confirmed'.")
    if status == "confirmed" and not (decision_ref and _DECISION_REF.match(decision_ref)):
        raise ValidationFailed(
            "DECISION_REF_REQUIRED", "A confirmed setting needs a decision-log reference such as 'BD-032'."
        )

    before = get(db, key, scope_type, scope_id)
    row = _row(db, key, scope_type, scope_id)
    if row is None:
        if expected_version is not None:
            raise PreconditionFailed("VERSION_MISMATCH", "The setting has not been stored yet; omit the version.")
        row = SystemSetting(
            key=key,
            scope_type=scope_type,
            scope_id=scope_id,
            value={"v": value},
            status=status,
            decision_ref=decision_ref if status == "confirmed" else None,
            updated_by=actor.principal_id,
        )
        db.add(row)
    else:
        if expected_version is not None and expected_version != row.version:
            raise PreconditionFailed("VERSION_MISMATCH", "The setting was changed by someone else; reload it.")
        row.value = {"v": value}
        row.status = status
        row.decision_ref = decision_ref if status == "confirmed" else None
        row.updated_by = actor.principal_id
    db.flush()
    audit.record(
        db,
        actor,
        "setting_changed",
        "setting",
        f"{key}@{scope_type}:{scope_id or '-'}",
        {
            "value": {"from": before.value, "to": value},
            "status": {"from": before.status, "to": status},
            "decision_ref": {"from": before.decision_ref, "to": row.decision_ref},
        },
    )
    return get(db, key, scope_type, scope_id)
