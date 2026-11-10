"""Opportunities and the sales pipeline."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, if_match_version, require
from mixt.core.db import get_session
from mixt.modules.pipeline import service as pipeline
from mixt.modules.pipeline.stages import stage_defs

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class StageOut(BaseModel):
    key: str
    name: str
    type: str
    sla_hours: int | None
    requires: list[str]


class OpportunityOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    title: str
    kind: str
    stage_key: str
    stage_name: str | None
    stage_type: str | None
    owner_user_id: uuid.UUID | None
    student_ids: list[uuid.UUID]
    budget_amount_minor: int | None
    budget_currency: str | None
    budget_notes: str | None
    expected_close_date: date | None
    lost_reason_code: str | None
    lost_notes: str | None
    nurture_until: date | None
    stage_entered_at: datetime
    closed_at: datetime | None
    sla_breached: bool
    version: int


class OpportunityIn(BaseModel):
    account_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    kind: str = "new_business"
    owner_user_id: uuid.UUID | None = None
    student_ids: list[uuid.UUID] = Field(default_factory=list)


class OpportunityPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    owner_user_id: uuid.UUID | None = None
    budget_amount_minor: int | None = None
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3)
    budget_notes: str | None = Field(default=None, max_length=1000)
    expected_close_date: date | None = None
    student_ids: list[uuid.UUID] | None = None


class MoveIn(BaseModel):
    to_stage: str
    note: str | None = Field(default=None, max_length=2000)
    lost_reason: str | None = None
    lost_notes: str | None = Field(default=None, max_length=2000)
    nurture_until: date | None = None


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_stage: str | None
    to_stage: str
    note: str | None
    changed_by: uuid.UUID
    changed_at: datetime


def _out(view: pipeline.OpportunityView) -> OpportunityOut:
    o = view.opportunity
    return OpportunityOut(
        id=o.id,
        account_id=o.account_id,
        title=o.title,
        kind=o.kind,
        stage_key=o.stage_key,
        stage_name=view.stage.name if view.stage else None,
        stage_type=view.stage.type if view.stage else None,
        owner_user_id=o.owner_user_id,
        student_ids=view.student_ids,
        budget_amount_minor=o.budget_amount_minor,
        budget_currency=o.budget_currency,
        budget_notes=o.budget_notes,
        expected_close_date=o.expected_close_date,
        lost_reason_code=o.lost_reason_code,
        lost_notes=o.lost_notes,
        nurture_until=o.nurture_until,
        stage_entered_at=o.stage_entered_at,
        closed_at=o.closed_at,
        sla_breached=view.sla_breached,
        version=o.version,
    )


@router.get("/stages", response_model=list[StageOut])
def stages(
    _: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[StageOut]:
    return [
        StageOut(key=s.key, name=s.name, type=s.type, sla_hours=s.sla_hours, requires=list(s.requires))
        for s in stage_defs(db)
    ]


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(
    stage: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    open_only: bool = False,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> list[OpportunityOut]:
    views = pipeline.list_opportunities(db, auth.access, stage, owner_user_id, account_id, open_only, before_id, limit)
    return [_out(v) for v in views]


@router.post("/opportunities", response_model=OpportunityOut, status_code=201)
def create(
    body: OpportunityIn,
    response: Response,
    auth: AuthContext = Depends(require("crm.opportunities.manage")),
    db: Session = Depends(get_session),
) -> OpportunityOut:
    view = pipeline.create_opportunity(
        db,
        auth.actor,
        auth.access,
        body.account_id,
        body.title,
        body.kind,
        body.owner_user_id,
        "owner_user_id" in body.model_fields_set,
        body.student_ids,
    )
    response.headers["ETag"] = f'"{view.opportunity.version}"'
    return _out(view)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def get(
    opportunity_id: uuid.UUID,
    response: Response,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> OpportunityOut:
    view = pipeline.get_opportunity(db, auth.access, opportunity_id)
    response.headers["ETag"] = f'"{view.opportunity.version}"'
    return _out(view)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def update(
    opportunity_id: uuid.UUID,
    body: OpportunityPatchIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.opportunities.manage")),
    db: Session = Depends(get_session),
) -> OpportunityOut:
    view = pipeline.update_opportunity(
        db, auth.actor, auth.access, opportunity_id, version, body.model_dump(exclude_unset=True)
    )
    response.headers["ETag"] = f'"{view.opportunity.version}"'
    return _out(view)


@router.post("/opportunities/{opportunity_id}/move", response_model=OpportunityOut)
def move(
    opportunity_id: uuid.UUID,
    body: MoveIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.opportunities.manage")),
    db: Session = Depends(get_session),
) -> OpportunityOut:
    view = pipeline.move_stage(
        db,
        auth.actor,
        auth.access,
        opportunity_id,
        version,
        body.to_stage,
        body.note,
        body.lost_reason,
        body.lost_notes,
        body.nurture_until,
    )
    response.headers["ETag"] = f'"{view.opportunity.version}"'
    return _out(view)


@router.get("/opportunities/{opportunity_id}/history", response_model=list[HistoryOut])
def history(
    opportunity_id: uuid.UUID,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> list[HistoryOut]:
    return [HistoryOut.model_validate(h) for h in pipeline.stage_history(db, auth.access, opportunity_id)]
