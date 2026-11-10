"""Leads: manual entry, review, campaigns, spreadsheet import, duplicates and merge."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api import throttle
from mixt.api.deps import AuthContext, require
from mixt.core.db import get_session
from mixt.core.errors import ValidationFailed
from mixt.modules.leads import importer
from mixt.modules.leads import service as leads
from mixt.modules.leads.models import Lead, LeadImportBatch

router = APIRouter(tags=["leads"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LeadIn(BaseModel):
    source: str = "manual"
    household_name: str | None = Field(default=None, max_length=200)
    guardian_first_name: str | None = Field(default=None, max_length=100)
    guardian_last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    student_first_name: str | None = Field(default=None, max_length=100)
    student_curriculum: str | None = None
    student_grade: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=4000)
    campaign_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    utm: dict[str, str] | None = None


class LeadOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    campaign_id: uuid.UUID | None
    status: str
    status_reason: str | None
    submitted_name: str | None
    submitted_country: str | None
    account_id: uuid.UUID | None  # hidden (null) when the household belongs to someone you cannot see
    linked_to_hidden_household: bool
    received_at: datetime


class IntakeOut(LeadOut):
    created_household: bool
    opportunity_id: uuid.UUID | None
    duplicate_candidates: int


class ReviewIn(BaseModel):
    decision: str
    note: str = Field(max_length=500)


class SourceOut(_Out):
    code: str
    name: str
    manual_entry_allowed: bool


class CampaignIn(BaseModel):
    source: str
    name: str = Field(min_length=1, max_length=120)
    market_id: uuid.UUID | None = None


class CampaignOut(_Out):
    id: uuid.UUID
    lead_source_id: uuid.UUID
    name: str
    market_id: uuid.UUID | None
    status: str


class ImportOut(BaseModel):
    id: uuid.UUID
    file_name: str
    status: str
    row_count: int
    valid_count: int
    error_count: int
    imported_count: int
    rows: list[dict[str, Any]]
    note: str | None


class DuplicateOut(_Out):
    id: uuid.UUID
    account_id: uuid.UUID
    candidate_account_id: uuid.UUID
    reason: str
    score: float | None
    status: str
    created_at: datetime


class MergeIn(BaseModel):
    survivor_account_id: uuid.UUID
    merged_account_id: uuid.UUID


class MergeOut(BaseModel):
    id: uuid.UUID
    surviving_id: uuid.UUID
    merged_id: uuid.UUID
    merged_at: datetime


def _lead_out(db: Session, auth: AuthContext, lead: Lead) -> dict[str, Any]:
    visible = leads.account_visible_for(db, auth.access, lead)
    return {
        "id": lead.id,
        "source_id": lead.lead_source_id,
        "campaign_id": lead.campaign_id,
        "status": lead.status,
        "status_reason": lead.status_reason,
        "submitted_name": lead.submitted_name,
        "submitted_country": lead.submitted_country,
        "account_id": lead.account_id if visible else None,
        "linked_to_hidden_household": lead.account_id is not None and not visible,
        "received_at": lead.received_at,
    }


def _import_out(batch: LeadImportBatch) -> ImportOut:
    return ImportOut(
        id=batch.id,
        file_name=batch.file_name,
        status=batch.status,
        row_count=batch.row_count,
        valid_count=batch.valid_count,
        error_count=batch.error_count,
        imported_count=batch.imported_count,
        rows=batch.report.get("rows", []),
        note=batch.report.get("note"),
    )


@router.get("/leads/sources", response_model=list[SourceOut])
def sources(_: AuthContext = Depends(require("leads.read")), db: Session = Depends(get_session)) -> list[SourceOut]:
    return [SourceOut.model_validate(s) for s in leads.list_sources(db)]


@router.get("/leads/campaigns", response_model=list[CampaignOut])
def campaigns(_: AuthContext = Depends(require("leads.read")), db: Session = Depends(get_session)) -> list[CampaignOut]:
    return [CampaignOut.model_validate(c) for c in leads.list_campaigns(db)]


@router.post("/leads/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(
    body: CampaignIn, auth: AuthContext = Depends(require("leads.campaigns.manage")), db: Session = Depends(get_session)
) -> CampaignOut:
    campaign = leads.create_campaign(db, auth.actor, auth.access, body.source, body.name, body.market_id)
    return CampaignOut.model_validate(campaign)


@router.post("/leads", response_model=IntakeOut, status_code=201)
def create_lead(
    body: LeadIn, auth: AuthContext = Depends(require("leads.create")), db: Session = Depends(get_session)
) -> IntakeOut:
    data = leads.LeadInput(
        source_code=body.source,
        household_name=body.household_name,
        guardian_first_name=body.guardian_first_name,
        guardian_last_name=body.guardian_last_name,
        email=body.email,
        phone=body.phone,
        country=body.country,
        student_first_name=body.student_first_name,
        student_curriculum=body.student_curriculum,
        student_grade=body.student_grade,
        message=body.message,
        campaign_id=body.campaign_id,
        utm=body.utm,
    )
    explicit = "owner_user_id" in body.model_fields_set
    result = leads.intake(db, auth.actor, auth.access, data, body.owner_user_id, explicit)
    return IntakeOut(
        **_lead_out(db, auth, result.lead),
        created_household=result.created_account,
        opportunity_id=result.opportunity_id if result.account_visible else None,
        duplicate_candidates=result.duplicate_candidates,
    )


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    status: str | None = None,
    source: str | None = None,
    campaign_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
    auth: AuthContext = Depends(require("leads.read")),
    db: Session = Depends(get_session),
) -> list[LeadOut]:
    rows = leads.list_leads(db, auth.access, status, source, campaign_id, before_id, limit)
    return [LeadOut(**_lead_out(db, auth, lead)) for lead in rows]


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: uuid.UUID, auth: AuthContext = Depends(require("leads.read")), db: Session = Depends(get_session)
) -> LeadOut:
    return LeadOut(**_lead_out(db, auth, leads.get_lead(db, auth.access, lead_id)))


@router.post("/leads/{lead_id}/review", response_model=LeadOut)
def review_lead(
    lead_id: uuid.UUID,
    body: ReviewIn,
    auth: AuthContext = Depends(require("leads.review")),
    db: Session = Depends(get_session),
) -> LeadOut:
    lead = leads.review_lead(db, auth.actor, auth.access, lead_id, body.decision, body.note)
    return LeadOut(**_lead_out(db, auth, lead))


@router.post("/leads/imports", response_model=ImportOut, status_code=201)
def upload_import(
    file: UploadFile = File(...),
    default_owner_user_id: uuid.UUID | None = Form(default=None),
    campaign_id: uuid.UUID | None = Form(default=None),
    auth: AuthContext = Depends(require("leads.import")),
    db: Session = Depends(get_session),
) -> ImportOut:
    # A plain (threaded) handler: the import does synchronous database work, which must not block
    # the event loop that serves everyone else's requests.
    throttle.enforce("import_per_user", str(auth.user.id))
    content = file.file.read(importer.MAX_BYTES + 1)
    if not content:
        raise ValidationFailed("FILE_EMPTY", "The uploaded file is empty.")
    batch = leads.validate_import(
        db, auth.actor, auth.access, file.filename or "upload.csv", content, default_owner_user_id, campaign_id
    )
    return _import_out(batch)


@router.get("/leads/imports/{batch_id}", response_model=ImportOut)
def get_import(
    batch_id: uuid.UUID, auth: AuthContext = Depends(require("leads.import")), db: Session = Depends(get_session)
) -> ImportOut:
    return _import_out(leads.get_import(db, auth.access, batch_id))


@router.post("/leads/imports/{batch_id}/commit", response_model=ImportOut)
def commit_import(
    batch_id: uuid.UUID, auth: AuthContext = Depends(require("leads.import")), db: Session = Depends(get_session)
) -> ImportOut:
    return _import_out(leads.commit_import(db, auth.actor, auth.access, batch_id))


@router.post("/leads/imports/{batch_id}/discard", response_model=ImportOut)
def discard_import(
    batch_id: uuid.UUID, auth: AuthContext = Depends(require("leads.import")), db: Session = Depends(get_session)
) -> ImportOut:
    return _import_out(leads.discard_import(db, auth.actor, auth.access, batch_id))


@router.get("/crm/duplicates", response_model=list[DuplicateOut])
def duplicates(
    status: str = "open", auth: AuthContext = Depends(require("crm.accounts.merge")), db: Session = Depends(get_session)
) -> list[DuplicateOut]:
    return [DuplicateOut.model_validate(d) for d in leads.list_duplicates(db, auth.access, status)]


@router.post("/crm/duplicates/{candidate_id}/dismiss", response_model=DuplicateOut)
def dismiss(
    candidate_id: uuid.UUID,
    auth: AuthContext = Depends(require("crm.accounts.merge")),
    db: Session = Depends(get_session),
) -> DuplicateOut:
    return DuplicateOut.model_validate(leads.dismiss_duplicate(db, auth.actor, auth.access, candidate_id))


@router.post("/crm/merges", response_model=MergeOut, status_code=201)
def merge(
    body: MergeIn, auth: AuthContext = Depends(require("crm.accounts.merge")), db: Session = Depends(get_session)
) -> MergeOut:
    record = leads.merge_accounts(db, auth.actor, auth.access, body.survivor_account_id, body.merged_account_id)
    return MergeOut(
        id=record.id, surviving_id=record.surviving_id, merged_id=record.merged_id, merged_at=record.merged_at
    )
