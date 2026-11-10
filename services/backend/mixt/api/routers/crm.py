"""CRM: households (accounts), contacts, contact points, consents, students."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, if_match_version, require
from mixt.core.db import get_session
from mixt.modules.crm import service as crm

router = APIRouter(prefix="/crm", tags=["crm"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountOut(_Out):
    id: uuid.UUID
    account_number: str
    kind: str
    display_name: str
    country_of_residence: str | None
    market_id: uuid.UUID | None
    market_confirmed_at: datetime | None
    market_confirmation_note: str | None
    timezone: str | None
    preferred_language: str | None
    lifecycle_stage: str
    owner_user_id: uuid.UUID | None
    is_vip: bool
    status: str
    created_at: datetime
    updated_at: datetime
    version: int


class AccountCreateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    kind: str = "household"
    country_of_residence: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    preferred_language: str | None = None
    owner_user_id: uuid.UUID | None = None
    is_vip: bool = False


class AccountPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    country_of_residence: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    preferred_language: str | None = None
    owner_user_id: uuid.UUID | None = None
    is_vip: bool | None = None
    lifecycle_stage: str | None = None


class MarketConfirmationIn(BaseModel):
    market_id: uuid.UUID
    note: str = Field(max_length=500)


class ContactOut(_Out):
    id: uuid.UUID
    account_id: uuid.UUID
    role: str
    first_name: str | None
    last_name: str | None
    preferred_name: str | None
    relationship_to_students: str | None
    is_primary: bool
    is_decision_maker: bool | None
    preferred_language: str | None
    timezone: str | None
    version: int


class ContactIn(BaseModel):
    role: str
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    relationship_to_students: str | None = Field(default=None, max_length=100)
    is_primary: bool = False
    is_decision_maker: bool | None = None
    preferred_language: str | None = None
    timezone: str | None = None


class ContactPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    relationship_to_students: str | None = Field(default=None, max_length=100)
    is_primary: bool | None = None
    is_decision_maker: bool | None = None
    preferred_language: str | None = None
    timezone: str | None = None


class ContactPointOut(_Out):
    id: uuid.UUID
    kind: str
    value: str
    is_primary: bool
    is_verified: bool
    status: str


class ContactPointIn(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=320)
    is_primary: bool = False


class ContactPointCreatedOut(ContactPointOut):
    possible_duplicate: bool


class ConsentOut(_Out):
    id: uuid.UUID
    contact_point_id: uuid.UUID | None
    purpose: str
    status: str
    legal_basis: str
    source: str
    evidence: dict[str, Any]
    captured_at: datetime
    captured_by: uuid.UUID


class ConsentIn(BaseModel):
    purpose: str
    status: str
    legal_basis: str
    source: str
    evidence: dict[str, Any]
    contact_point_id: uuid.UUID | None = None


class ConsentsOut(BaseModel):
    current: list[ConsentOut]
    history: list[ConsentOut]


class SubjectOut(_Out):
    id: uuid.UUID
    subject_name: str
    exam_board_id: uuid.UUID | None
    qualification_id: uuid.UUID | None
    current_grade: str | None
    target_grade: str | None
    priority: int | None
    status: str


class ExamOut(_Out):
    id: uuid.UUID
    student_subject_id: uuid.UUID | None
    exam_board_id: uuid.UUID | None
    qualification_id: uuid.UUID | None
    exam_session: str | None
    exam_date: date | None
    paper_code: str | None
    source: str
    is_confirmed: bool


class StudentOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    contact_id: uuid.UUID | None
    first_name: str
    last_name: str | None
    preferred_name: str | None
    birth_year: int | None
    curriculum_id: uuid.UUID | None
    grade_text: str | None
    school_name: str | None
    country_of_study: str | None
    timezone: str | None
    goals: str | None
    status: str
    learning_needs: str | None
    learning_needs_restricted: bool
    subjects: list[SubjectOut]
    exams: list[ExamOut]
    version: int


class StudentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    birth_year: int | None = None
    curriculum_code: str | None = None
    grade_text: str | None = Field(default=None, max_length=100)
    school_name: str | None = Field(default=None, max_length=200)
    country_of_study: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    goals: str | None = Field(default=None, max_length=2000)
    status: str = "prospective"
    contact_id: uuid.UUID | None = None
    learning_needs: str | None = Field(default=None, max_length=4000)


class StudentPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    birth_year: int | None = None
    curriculum_code: str | None = None
    grade_text: str | None = Field(default=None, max_length=100)
    school_name: str | None = Field(default=None, max_length=200)
    country_of_study: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    goals: str | None = Field(default=None, max_length=2000)
    status: str | None = None
    learning_needs: str | None = Field(default=None, max_length=4000)


class SubjectIn(BaseModel):
    subject_name: str = Field(min_length=1, max_length=100)
    exam_board_code: str | None = None
    qualification_code: str | None = None
    current_grade: str | None = Field(default=None, max_length=20)
    target_grade: str | None = Field(default=None, max_length=20)
    priority: int | None = Field(default=None, ge=1, le=20)
    status: str = "interested"


class ExamIn(BaseModel):
    student_subject_id: uuid.UUID | None = None
    exam_session: str | None = Field(default=None, max_length=50)
    exam_date: date | None = None
    paper_code: str | None = Field(default=None, max_length=50)
    source: str = "staff"
    is_confirmed: bool = False


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


def _student_out(view: crm.StudentView) -> StudentOut:
    s = view.student
    return StudentOut(
        id=s.id,
        account_id=s.account_id,
        contact_id=s.contact_id,
        first_name=s.first_name,
        last_name=s.last_name,
        preferred_name=s.preferred_name,
        birth_year=s.birth_year,
        curriculum_id=s.curriculum_id,
        grade_text=s.grade_text,
        school_name=s.school_name,
        country_of_study=s.country_of_study,
        timezone=s.timezone,
        goals=s.goals,
        status=s.status,
        learning_needs=view.learning_needs,
        learning_needs_restricted=view.learning_needs_restricted,
        subjects=[SubjectOut.model_validate(x) for x in view.subjects],
        exams=[ExamOut.model_validate(x) for x in view.exams],
        version=s.version,
    )


# ------------------------------------------------------------------ accounts


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    search: str | None = None,
    lifecycle_stage: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> list[AccountOut]:
    rows = crm.list_accounts(db, auth.access, search, lifecycle_stage, owner_user_id, before_id, limit)
    return [AccountOut.model_validate(a) for a in rows]


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(
    body: AccountCreateIn,
    response: Response,
    auth: AuthContext = Depends(require("crm.accounts.create")),
    db: Session = Depends(get_session),
) -> AccountOut:
    account = crm.create_account(
        db,
        auth.actor,
        auth.access,
        body.display_name,
        body.kind,
        body.country_of_residence,
        body.timezone,
        body.preferred_language,
        body.owner_user_id,
        "owner_user_id" in body.model_fields_set,
        body.is_vip,
    )
    _etag(response, account.version)
    return AccountOut.model_validate(account)


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(
    account_id: uuid.UUID,
    response: Response,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> AccountOut:
    account = crm.get_account(db, auth.access, account_id)
    _etag(response, account.version)
    return AccountOut.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID,
    body: AccountPatchIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> AccountOut:
    account = crm.update_account(db, auth.actor, auth.access, account_id, version, body.model_dump(exclude_unset=True))
    _etag(response, account.version)
    return AccountOut.model_validate(account)


@router.post("/accounts/{account_id}/market-confirmation", response_model=AccountOut)
def confirm_market(
    account_id: uuid.UUID,
    body: MarketConfirmationIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.market.confirm")),
    db: Session = Depends(get_session),
) -> AccountOut:
    account = crm.confirm_market(db, auth.actor, auth.access, account_id, body.market_id, body.note, version)
    _etag(response, account.version)
    return AccountOut.model_validate(account)


# ------------------------------------------------------------------ contacts


@router.get("/accounts/{account_id}/contacts", response_model=list[ContactOut])
def list_contacts(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[ContactOut]:
    return [ContactOut.model_validate(c) for c in crm.list_contacts(db, auth.access, account_id)]


@router.post("/accounts/{account_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(
    account_id: uuid.UUID,
    body: ContactIn,
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> ContactOut:
    return ContactOut.model_validate(crm.add_contact(db, auth.actor, auth.access, account_id, body.model_dump()))


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: uuid.UUID,
    body: ContactPatchIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> ContactOut:
    contact = crm.update_contact(db, auth.actor, auth.access, contact_id, version, body.model_dump(exclude_unset=True))
    _etag(response, contact.version)
    return ContactOut.model_validate(contact)


@router.get("/contacts/{contact_id}/contact-points", response_model=list[ContactPointOut])
def list_contact_points(
    contact_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[ContactPointOut]:
    return [ContactPointOut.model_validate(p) for p in crm.list_contact_points(db, auth.access, contact_id)]


@router.post("/contacts/{contact_id}/contact-points", response_model=ContactPointCreatedOut, status_code=201)
def add_contact_point(
    contact_id: uuid.UUID,
    body: ContactPointIn,
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> ContactPointCreatedOut:
    added = crm.add_contact_point(db, auth.actor, auth.access, contact_id, body.kind, body.value, body.is_primary)
    base = ContactPointOut.model_validate(added.contact_point)
    return ContactPointCreatedOut(**base.model_dump(), possible_duplicate=added.possible_duplicate)


@router.get("/contacts/{contact_id}/consents", response_model=ConsentsOut)
def consents(
    contact_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> ConsentsOut:
    return ConsentsOut(
        current=[ConsentOut.model_validate(c) for c in crm.current_consents(db, auth.access, contact_id)],
        history=[ConsentOut.model_validate(c) for c in crm.consent_history(db, auth.access, contact_id)],
    )


@router.post("/contacts/{contact_id}/consents", response_model=ConsentOut, status_code=201)
def record_consent(
    contact_id: uuid.UUID,
    body: ConsentIn,
    auth: AuthContext = Depends(require("crm.consents.record")),
    db: Session = Depends(get_session),
) -> ConsentOut:
    consent = crm.record_consent(
        db,
        auth.actor,
        auth.access,
        contact_id,
        body.purpose,
        body.status,
        body.legal_basis,
        body.source,
        body.evidence,
        body.contact_point_id,
    )
    return ConsentOut.model_validate(consent)


# ------------------------------------------------------------------ students


@router.get("/accounts/{account_id}/students", response_model=list[StudentOut])
def list_students(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[StudentOut]:
    return [_student_out(v) for v in crm.list_students(db, auth.access, account_id)]


@router.post("/accounts/{account_id}/students", response_model=StudentOut, status_code=201)
def create_student(
    account_id: uuid.UUID,
    body: StudentIn,
    auth: AuthContext = Depends(require("crm.students.manage")),
    db: Session = Depends(get_session),
) -> StudentOut:
    data = body.model_dump(exclude_unset=True)
    return _student_out(crm.create_student(db, auth.actor, auth.access, account_id, data))


@router.get("/students/{student_id}", response_model=StudentOut)
def get_student(
    student_id: uuid.UUID,
    response: Response,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> StudentOut:
    view = crm.view_student(db, auth.access, student_id)
    _etag(response, view.student.version)
    return _student_out(view)


@router.patch("/students/{student_id}", response_model=StudentOut)
def update_student(
    student_id: uuid.UUID,
    body: StudentPatchIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.students.manage")),
    db: Session = Depends(get_session),
) -> StudentOut:
    view = crm.update_student(db, auth.actor, auth.access, student_id, version, body.model_dump(exclude_unset=True))
    _etag(response, view.student.version)
    return _student_out(view)


@router.post("/students/{student_id}/subjects", response_model=SubjectOut, status_code=201)
def add_subject(
    student_id: uuid.UUID,
    body: SubjectIn,
    auth: AuthContext = Depends(require("crm.students.manage")),
    db: Session = Depends(get_session),
) -> SubjectOut:
    return SubjectOut.model_validate(
        crm.add_student_subject(db, auth.actor, auth.access, student_id, body.model_dump())
    )


@router.post("/students/{student_id}/exams", response_model=ExamOut, status_code=201)
def add_exam(
    student_id: uuid.UUID,
    body: ExamIn,
    auth: AuthContext = Depends(require("crm.students.manage")),
    db: Session = Depends(get_session),
) -> ExamOut:
    return ExamOut.model_validate(crm.add_student_exam(db, auth.actor, auth.access, student_id, body.model_dump()))


class SchedulingPreferencesIn(BaseModel):
    timezone: str
    preferred_weekdays: list[int] | None = None
    preferred_windows: list[dict[str, str]] | None = None
    lessons_per_week: float | None = Field(default=None, ge=0, le=21)
    preferred_session_minutes: int | None = Field(default=None, ge=15, le=240)
    notes: str | None = Field(default=None, max_length=1000)


class SchedulingPreferencesOut(BaseModel):
    student_id: uuid.UUID
    timezone: str
    preferred_weekdays: list[int] | None
    preferred_windows: list[dict[str, str]] | None
    lessons_per_week: float | None
    preferred_session_minutes: int | None
    notes: str | None


def _prefs_out(pref: Any) -> SchedulingPreferencesOut:
    return SchedulingPreferencesOut(
        student_id=pref.student_id,
        timezone=pref.timezone,
        preferred_weekdays=pref.preferred_weekdays,
        preferred_windows=(pref.preferred_windows or {}).get("windows"),
        lessons_per_week=float(pref.lessons_per_week) if pref.lessons_per_week is not None else None,
        preferred_session_minutes=pref.preferred_session_minutes,
        notes=pref.notes,
    )


@router.get("/students/{student_id}/scheduling-preferences", response_model=SchedulingPreferencesOut | None)
def get_preferences(
    student_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> SchedulingPreferencesOut | None:
    pref = crm.get_scheduling_preferences(db, auth.access, student_id)
    return _prefs_out(pref) if pref else None


@router.put("/students/{student_id}/scheduling-preferences", response_model=SchedulingPreferencesOut)
def set_preferences(
    student_id: uuid.UUID,
    body: SchedulingPreferencesIn,
    auth: AuthContext = Depends(require("crm.students.manage")),
    db: Session = Depends(get_session),
) -> SchedulingPreferencesOut:
    data = body.model_dump()
    if data["lessons_per_week"] is not None:
        data["lessons_per_week"] = Decimal(str(data["lessons_per_week"]))
    return _prefs_out(crm.set_scheduling_preferences(db, auth.actor, auth.access, student_id, data))
