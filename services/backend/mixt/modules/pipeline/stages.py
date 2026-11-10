"""Pipeline stage configuration (setting ``crm.pipeline_stages``) and the checks a stage can require."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mixt.core.errors import ValidationFailed
from mixt.modules.pipeline.models import Opportunity
from mixt.modules.settings import service as settings
from mixt.modules.settings.registry import STAGE_CHECKS


@dataclass(frozen=True)
class StageDef:
    key: str
    name: str
    type: str  # open | won | lost
    sla_hours: int | None
    requires: tuple[str, ...]
    position: int


def stage_defs(db: Session) -> list[StageDef]:
    raw = settings.get_value(db, "crm.pipeline_stages")
    return [
        StageDef(s["key"], s["name"], s["type"], s.get("sla_hours"), tuple(s["requires"]), i) for i, s in enumerate(raw)
    ]


def stage_map(db: Session) -> dict[str, StageDef]:
    return {s.key: s for s in stage_defs(db)}


def entry_stage(db: Session) -> StageDef:
    return stage_defs(db)[0]


def lost_reason_codes(db: Session) -> set[str]:
    return {r["code"] for r in settings.get_value(db, "crm.lost_reasons")}


def validate_stage_config(db: Session, value: Any) -> None:
    """Semantic checks for a new stage list (the JSON schema checks the shape)."""
    keys = [s["key"] for s in value]
    if len(keys) != len(set(keys)):
        raise ValidationFailed("DUPLICATE_STAGE_KEYS", "Stage keys must be unique.")
    types = {s["type"] for s in value}
    if not {"won", "lost"} <= types:
        raise ValidationFailed("STAGES_NEED_WON_AND_LOST", "The pipeline needs at least one won and one lost stage.")
    if value[0]["type"] != "open":
        raise ValidationFailed("FIRST_STAGE_MUST_BE_OPEN", "The first stage is where new opportunities start.")
    unknown = {c for s in value for c in s["requires"]} - set(STAGE_CHECKS)
    if unknown:
        raise ValidationFailed("UNKNOWN_STAGE_CHECKS", f"Unknown checks: {', '.join(sorted(unknown))}.")
    in_use = set(db.scalars(select(Opportunity.stage_key).group_by(Opportunity.stage_key)))
    removed = in_use - set(keys)
    if removed:
        rows = db.execute(
            select(Opportunity.stage_key, func.count())
            .where(Opportunity.stage_key.in_(removed))
            .group_by(Opportunity.stage_key)
        ).all()
        counts = {row[0]: row[1] for row in rows}  # dict(result) would treat the result as a mapping
        detail = ", ".join(f"{k} ({counts[k]})" for k in sorted(removed))
        raise ValidationFailed("STAGE_IN_USE", f"Move opportunities out of these stages first: {detail}.")


def validate_lost_reasons(db: Session, value: Any) -> None:
    codes = [r["code"] for r in value]
    if len(codes) != len(set(codes)):
        raise ValidationFailed("DUPLICATE_LOST_REASONS", "Lost reason codes must be unique.")
    in_use = {c for c in db.scalars(select(Opportunity.lost_reason_code)) if c is not None}
    removed = in_use - set(codes)
    if removed:
        raise ValidationFailed("LOST_REASON_IN_USE", f"Still used by lost opportunities: {', '.join(sorted(removed))}.")


def register() -> None:
    settings.register_validator("crm.pipeline_stages", validate_stage_config)
    settings.register_validator("crm.lost_reasons", validate_lost_reasons)
