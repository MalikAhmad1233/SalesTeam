"""Pricing administration (Phase 2b): sheet imports, rules and the rule tester, confidential customer
pricing and promotions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, current_auth, require
from mixt.core.db import get_session
from mixt.core.errors import ValidationFailed
from mixt.modules.pricing import imports, promotions, rule_service, special
from mixt.modules.pricing.rules import FACT_TYPES, OPERATORS

router = APIRouter(tags=["pricing"])


# ------------------------------------------------------------------------------------ imports


class ImportRowOut(BaseModel):
    row_no: int
    raw: dict[str, Any]
    errors: list[str]


class PricingImportOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    uploaded_at: datetime
    error_count: int
    report: dict[str, Any]
    rows: list[ImportRowOut]
    applied_version_ids: list[str] | None


class ApplyImportIn(BaseModel):
    change_type: Literal["price_change", "correction"]
    source_document: str = Field(max_length=500)
    source_received_on: date
    change_summary: str = Field(max_length=2000)


def _import_out(batch: imports.Batch, rows: list[Any]) -> PricingImportOut:
    return PricingImportOut(
        id=batch.id,
        filename=batch.filename,
        status=batch.status,
        uploaded_at=batch.uploaded_at,
        error_count=batch.error_count,
        report=batch.report,
        rows=[ImportRowOut(row_no=r.row_no, raw=r.raw, errors=r.errors) for r in rows],
        applied_version_ids=batch.applied_version_ids,
    )


@router.get("/pricing/imports/template", response_class=PlainTextResponse)
def import_template(_auth: AuthContext = Depends(require("pricing.import"))) -> PlainTextResponse:
    return PlainTextResponse(
        imports.TEMPLATE + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pricing-template.csv"'},
    )


@router.post("/pricing/imports", response_model=PricingImportOut, status_code=201)
def upload_import(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require("pricing.import")),
    db: Session = Depends(get_session),
) -> PricingImportOut:
    content = file.file.read(imports.MAX_BYTES + 1)
    if not content:
        raise ValidationFailed("FILE_EMPTY", "The uploaded file is empty.")
    batch = imports.validate(db, auth.actor, auth.access, file.filename or "pricing.csv", content)
    return _import_out(*imports.get_batch(db, auth.access, batch.id))


@router.get("/pricing/imports/{batch_id}", response_model=PricingImportOut)
def get_import(
    batch_id: uuid.UUID, auth: AuthContext = Depends(require("pricing.import")), db: Session = Depends(get_session)
) -> PricingImportOut:
    return _import_out(*imports.get_batch(db, auth.access, batch_id))


@router.post("/pricing/imports/{batch_id}/apply", response_model=PricingImportOut)
def apply_import(
    batch_id: uuid.UUID,
    body: ApplyImportIn,
    auth: AuthContext = Depends(require("pricing.import")),
    db: Session = Depends(get_session),
) -> PricingImportOut:
    imports.apply(
        db,
        auth.actor,
        auth.access,
        batch_id,
        change_type=body.change_type,
        source_document=body.source_document,
        source_received_on=body.source_received_on,
        change_summary=body.change_summary,
    )
    return _import_out(*imports.get_batch(db, auth.access, batch_id))


@router.post("/pricing/imports/{batch_id}/discard", response_model=PricingImportOut)
def discard_import(
    batch_id: uuid.UUID, auth: AuthContext = Depends(require("pricing.import")), db: Session = Depends(get_session)
) -> PricingImportOut:
    imports.discard(db, auth.actor, auth.access, batch_id)
    return _import_out(*imports.get_batch(db, auth.access, batch_id))


# ------------------------------------------------------------------------------------ rules


class RuleOut(BaseModel):
    id: uuid.UUID
    code: str
    rule_version: int
    name: str
    kind: str
    definition: dict[str, Any]
    description: str | None
    decision_ref: str | None
    status: str
    created_at: datetime
    approved_at: datetime | None


class RuleIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,40}$")
    name: str = Field(max_length=200)
    kind: Literal["eligibility", "minimum_purchase"]
    definition: dict[str, Any]
    description: str | None = Field(default=None, max_length=2000)
    decision_ref: str | None = Field(default=None, max_length=16)


class RuleUpdateIn(BaseModel):
    name: str = Field(max_length=200)
    definition: dict[str, Any]
    description: str | None = Field(default=None, max_length=2000)
    decision_ref: str | None = Field(default=None, max_length=16)


class RuleTestIn(BaseModel):
    account_id: uuid.UUID


class RuleTestOut(BaseModel):
    result: bool
    trace: list[str]
    facts: dict[str, Any]
    min_quantity: str | None


class AttachRuleIn(BaseModel):
    kind: Literal["eligibility", "minimum_purchase"]
    rule_id: uuid.UUID | None


class FactOut(BaseModel):
    fact: str
    type: str
    operators: list[str]


def _rule(rule: rule_service.Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        code=rule.code,
        rule_version=rule.rule_version,
        name=rule.name,
        kind=rule.kind,
        definition=rule.definition,
        description=rule.description,
        decision_ref=rule.decision_ref,
        status=rule.status,
        created_at=rule.created_at,
        approved_at=rule.approved_at,
    )


@router.get("/pricing/rules/facts", response_model=list[FactOut])
def rule_facts(_auth: AuthContext = Depends(require("pricing.read"))) -> list[FactOut]:
    return [FactOut(fact=f, type=t, operators=sorted(OPERATORS[t])) for f, t in FACT_TYPES.items()]


@router.get("/pricing/rules", response_model=list[RuleOut])
def list_rules(
    auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> list[RuleOut]:
    return [_rule(r) for r in rule_service.list_rules(db, auth.access)]


@router.post("/pricing/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)) -> RuleOut:
    rule = rule_service.create_rule(
        db,
        auth.actor,
        auth.access,
        body.code,
        body.name,
        body.kind,
        body.definition,
        body.description,
        body.decision_ref,
    )
    return _rule(rule)


@router.put("/pricing/rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdateIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> RuleOut:
    rule = rule_service.update_draft(
        db, auth.actor, auth.access, rule_id, body.name, body.definition, body.description, body.decision_ref
    )
    return _rule(rule)


@router.post("/pricing/rules/{rule_id}/approve", response_model=RuleOut)
def approve_rule(
    rule_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> RuleOut:
    return _rule(rule_service.approve_rule(db, auth.actor, auth.access, rule_id))


@router.post("/pricing/rules/{rule_id}/retire", response_model=RuleOut)
def retire_rule(
    rule_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> RuleOut:
    return _rule(rule_service.retire_rule(db, auth.actor, auth.access, rule_id))


@router.post("/pricing/rules/{rule_id}/test", response_model=RuleTestOut)
def test_rule(
    rule_id: uuid.UUID, body: RuleTestIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> RuleTestOut:
    outcome = rule_service.try_rule(db, auth.access, rule_id, body.account_id)
    return RuleTestOut(
        result=outcome.result, trace=list(outcome.trace), facts=outcome.facts, min_quantity=outcome.min_quantity
    )


class FactsIn(BaseModel):
    facts: dict[str, Any]


@router.post("/pricing/rules/{rule_id}/evaluate", response_model=RuleTestOut)
def evaluate_rule(
    rule_id: uuid.UUID, body: FactsIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> RuleTestOut:
    outcome = rule_service.try_rule_with_facts(db, auth.access, rule_id, body.facts)
    rule = rule_service.get_rule(db, rule_id)
    minimum = str(rule.definition["min_quantity"]) if rule.kind == "minimum_purchase" else None
    return RuleTestOut(result=outcome.result, trace=list(outcome.trace), facts=body.facts, min_quantity=minimum)


@router.post("/pricing/assignments/{assignment_id}/rules", status_code=204)
def attach_rule(
    assignment_id: uuid.UUID,
    body: AttachRuleIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> None:
    rule_service.attach_rule(db, auth.actor, auth.access, assignment_id, body.kind, body.rule_id)


# ------------------------------------------------------------------------------------ special pricing


class SpecialOut(BaseModel):
    id: uuid.UUID
    price_book_id: uuid.UUID
    price_book_code: str
    price_book_name: str
    reason: str
    status: str
    valid_from: datetime
    valid_to: datetime | None
    requested_by: uuid.UUID
    approved_by: uuid.UUID | None
    close_reason: str | None
    created_at: datetime


class SpecialBookOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SpecialRequestIn(BaseModel):
    price_book_id: uuid.UUID
    reason: str = Field(max_length=2000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CloseIn(BaseModel):
    reason: str = Field(max_length=2000)


def _special(view: special.SpecialView) -> SpecialOut:
    a = view.assignment
    return SpecialOut(
        id=a.id,
        price_book_id=a.price_book_id,
        price_book_code=view.book_code,
        price_book_name=view.book_name,
        reason=a.reason,
        status=a.status,
        valid_from=a.valid_from,
        valid_to=a.valid_to,
        requested_by=a.requested_by,
        approved_by=a.approved_by,
        close_reason=a.close_reason,
        created_at=a.created_at,
    )


@router.get("/accounts/{account_id}/pricing/special", response_model=list[SpecialOut])
def list_special(
    account_id: uuid.UUID,
    auth: AuthContext = Depends(require("pricing.special.view")),
    db: Session = Depends(get_session),
) -> list[SpecialOut]:
    return [_special(v) for v in special.list_for_account(db, auth.access, account_id)]


@router.get("/accounts/{account_id}/pricing/special/books", response_model=list[SpecialBookOut])
def special_books(
    account_id: uuid.UUID,
    auth: AuthContext = Depends(require("pricing.special.request")),
    db: Session = Depends(get_session),
) -> list[SpecialBookOut]:
    return [
        SpecialBookOut(id=b.id, code=b.code, name=b.name) for b in special.restricted_books(db, auth.access, account_id)
    ]


@router.post("/accounts/{account_id}/pricing/special", response_model=SpecialOut, status_code=201)
def request_special(
    account_id: uuid.UUID,
    body: SpecialRequestIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> SpecialOut:
    view = special.request(
        db, auth.actor, auth.access, account_id, body.price_book_id, body.reason, body.valid_from, body.valid_to
    )
    return _special(view)


@router.post("/pricing/special/{assignment_id}/approve", response_model=SpecialOut)
def approve_special(
    assignment_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> SpecialOut:
    return _special(special.approve(db, auth.actor, auth.access, assignment_id))


@router.post("/pricing/special/{assignment_id}/{action}", response_model=SpecialOut)
def close_special(
    assignment_id: uuid.UUID,
    action: Literal["reject", "revoke"],
    body: CloseIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> SpecialOut:
    return _special(special.close(db, auth.actor, auth.access, assignment_id, action, body.reason))


# ------------------------------------------------------------------------------------ promotions


class TargetIn(BaseModel):
    price_book_version_id: uuid.UUID
    price_book_entry_id: uuid.UUID | None = None
    market_id: uuid.UUID | None = None


class PromotionIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,40}$")
    name: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    terms: str | None = Field(default=None, max_length=4000)
    kind: Literal["percent_off", "amount_off", "bonus_units"]
    value: dict[str, Any]
    starts_at: datetime
    ends_at: datetime
    targets: list[TargetIn] = Field(min_length=1, max_length=100)
    eligibility_rule_id: uuid.UUID | None = None
    stackable: bool = False
    max_redemptions: int | None = Field(default=None, ge=1)
    max_per_account: int = Field(default=1, ge=1)
    decision_ref: str | None = Field(default=None, max_length=16)


class PromotionOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    terms: str | None
    kind: str
    value: dict[str, Any]
    starts_at: datetime
    ends_at: datetime
    stackable: bool
    decision_ref: str | None
    status: str
    status_reason: str | None
    targets: list[TargetIn]
    activation_problems: list[str]


def _promotion(db: Session, row: promotions.PromotionRow) -> PromotionOut:
    return PromotionOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        terms=row.terms,
        kind=row.kind,
        value=row.value,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        stackable=row.stackable,
        decision_ref=row.decision_ref,
        status=row.status,
        status_reason=row.status_reason,
        targets=[
            TargetIn(
                price_book_version_id=t.price_book_version_id,  # always set by create()
                price_book_entry_id=t.price_book_entry_id,
                market_id=t.market_id,
            )
            for t in promotions.targets_of(db, row.id)
        ],
        activation_problems=promotions.activation_problems(db, row) if row.status == "approved" else [],
    )


@router.get("/pricing/promotions", response_model=list[PromotionOut])
def list_promotions(
    auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> list[PromotionOut]:
    return [_promotion(db, p) for p in promotions.list_promotions(db, auth.access)]


@router.post("/pricing/promotions", response_model=PromotionOut, status_code=201)
def create_promotion(
    body: PromotionIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> PromotionOut:
    row = promotions.create(
        db,
        auth.actor,
        auth.access,
        code=body.code,
        name=body.name,
        description=body.description,
        terms=body.terms,
        kind=body.kind,
        value=body.value,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        targets=[
            promotions.TargetIn(t.price_book_version_id, t.price_book_entry_id, t.market_id) for t in body.targets
        ],
        eligibility_rule_id=body.eligibility_rule_id,
        stackable=body.stackable,
        max_redemptions=body.max_redemptions,
        max_per_account=body.max_per_account,
        decision_ref=body.decision_ref,
    )
    return _promotion(db, row)


@router.post("/pricing/promotions/{promotion_id}/cancel", response_model=PromotionOut)
def cancel_promotion(
    promotion_id: uuid.UUID,
    body: CloseIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> PromotionOut:
    return _promotion(db, promotions.cancel(db, auth.actor, auth.access, promotion_id, body.reason))


@router.post("/pricing/promotions/{promotion_id}/{action}", response_model=PromotionOut)
def promotion_action(
    promotion_id: uuid.UUID,
    action: Literal["submit", "approve", "activate"],
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> PromotionOut:
    handler = {"submit": promotions.submit, "approve": promotions.approve, "activate": promotions.activate}[action]
    return _promotion(db, handler(db, auth.actor, auth.access, promotion_id))
