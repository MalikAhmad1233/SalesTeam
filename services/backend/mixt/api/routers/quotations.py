"""Quotations API (Phase 2c)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, current_auth, require
from mixt.core.db import get_session
from mixt.core.errors import Conflict
from mixt.core.money import Money, format_money
from mixt.modules.crm import service as crm
from mixt.modules.quotations import pdf
from mixt.modules.quotations import service as quotations
from mixt.modules.reference import service as reference

router = APIRouter(tags=["quotations"])


class LineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    student_id: uuid.UUID | None
    price_book_code: str
    price_book_version_no: int
    package_code: str
    display_name: str
    plan_type: str
    tier_label: str | None
    quantity: Decimal
    unit_type: str
    currency_code: str
    list_total_minor: int
    list_total_display: str
    promotion_code: str | None
    promotion_discount_minor: int
    bonus_units: Decimal | None
    discount_minor: int
    final_total_minor: int
    final_total_display: str
    special_pricing: bool
    benefits: list[str]


class ApprovalOut(BaseModel):
    decided_by_user_id: uuid.UUID
    capacity: str
    decision: str
    comment: str | None
    decided_at: datetime


class QuotationSummaryOut(BaseModel):
    id: uuid.UUID
    quote_number: str
    revision_no: int
    account_id: uuid.UUID
    status: str
    currency_code: str | None
    total_minor: int
    total_display: str | None
    valid_until: date | None
    created_at: datetime


class QuotationOut(QuotationSummaryOut):
    opportunity_id: uuid.UUID
    market_id: uuid.UUID
    status_reason: str | None
    subtotal_minor: int
    promotion_total_minor: int
    discount_total_minor: int
    tax_treatment: str | None
    discount_reason: str | None
    customer_note: str | None
    internal_note: str | None
    snapshot_hash: str | None
    issued_at: datetime | None
    issued_to_contact_id: uuid.UUID | None
    outcome_note: str | None
    lines: list[LineOut]
    approvals: list[ApprovalOut]
    needs: dict[str, Any]
    outstanding: list[str]
    checks: list[str]
    version: int


class CreateIn(BaseModel):
    account_id: uuid.UUID
    opportunity_id: uuid.UUID
    customer_note: str | None = Field(default=None, max_length=2000)


class UpdateIn(BaseModel):
    valid_until: date | None = None
    customer_note: str | None = Field(default=None, max_length=2000)
    internal_note: str | None = Field(default=None, max_length=2000)
    discount_reason: str | None = Field(default=None, max_length=2000)


class LineIn(BaseModel):
    entry_id: uuid.UUID
    student_id: uuid.UUID | None = None
    promotion_code: str | None = Field(default=None, max_length=60)
    discount_minor: int = Field(default=0, ge=0)


class ApproveIn(BaseModel):
    capacity: Literal["sales", "pricing"]
    valid_until: date | None = None
    comment: str | None = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(max_length=2000)


class IssueIn(BaseModel):
    contact_id: uuid.UUID


class OutcomeIn(BaseModel):
    outcome: Literal["accepted", "declined"]
    note: str = Field(max_length=2000)
    price_change_reconfirmed: bool = False


class RevisionOut(BaseModel):
    quotation: QuotationOut
    dropped: list[str]


def _money(db: Session, amount: int, currency: str | None) -> str | None:
    if not currency:
        return None
    return format_money(Money(amount, currency), reference.currency(db, currency).minor_units)


def _summary(db: Session, q: quotations.Quote) -> QuotationSummaryOut:
    return QuotationSummaryOut(
        id=q.id,
        quote_number=q.quote_number,
        revision_no=q.revision_no,
        account_id=q.account_id,
        status=q.status,
        currency_code=q.currency_code,
        total_minor=q.total_minor,
        total_display=_money(db, q.total_minor, q.currency_code),
        valid_until=q.valid_until,
        created_at=q.created_at,
    )


def _out(db: Session, view: quotations.QuoteView) -> QuotationOut:
    q = view.quote
    outstanding = sorted(quotations.outstanding(db, q)) if q.status == "pending_approval" else []
    return QuotationOut(
        **_summary(db, q).model_dump(),
        opportunity_id=q.opportunity_id,
        market_id=q.market_id,
        status_reason=q.status_reason,
        subtotal_minor=q.subtotal_minor,
        promotion_total_minor=q.promotion_total_minor,
        discount_total_minor=q.discount_total_minor,
        tax_treatment=q.tax_treatment,
        discount_reason=q.discount_reason,
        customer_note=q.customer_note,
        internal_note=q.internal_note,
        snapshot_hash=q.snapshot_hash,
        issued_at=q.issued_at,
        issued_to_contact_id=q.issued_to_contact_id,
        outcome_note=q.outcome_note,
        lines=[
            LineOut(
                id=line.id,
                line_no=line.line_no,
                student_id=line.student_id,
                price_book_code=line.price_book_code,
                price_book_version_no=line.price_book_version_no,
                package_code=line.package_code,
                display_name=line.display_name,
                plan_type=line.plan_type,
                tier_label=line.tier_label,
                quantity=Decimal(line.quantity),
                unit_type=line.unit_type,
                currency_code=line.currency_code,
                list_total_minor=line.list_total_minor,
                list_total_display=_money(db, line.list_total_minor, line.currency_code) or "",
                promotion_code=line.promotion_snapshot.get("code") if line.promotion_snapshot else None,
                promotion_discount_minor=line.promotion_discount_minor,
                bonus_units=Decimal(line.bonus_units) if line.bonus_units is not None else None,
                discount_minor=line.discount_minor,
                final_total_minor=line.final_total_minor,
                final_total_display=_money(db, line.final_total_minor, line.currency_code) or "",
                special_pricing=line.special_assignment_id is not None,
                benefits=list(line.benefits_snapshot),
            )
            for line in view.lines
        ],
        approvals=[
            ApprovalOut(
                decided_by_user_id=a.decided_by_user_id,
                capacity=a.capacity,
                decision=a.decision,
                comment=a.comment,
                decided_at=a.decided_at,
            )
            for a in view.approvals
        ],
        needs=view.needs,
        outstanding=outstanding,
        checks=view.checks,
        version=q.version,
    )


@router.get("/quotations/approvals", response_model=list[QuotationSummaryOut])
def approval_inbox(
    auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> list[QuotationSummaryOut]:
    return [_summary(db, q) for q in quotations.approval_inbox(db, auth.access)]


@router.get("/accounts/{account_id}/quotations", response_model=list[QuotationSummaryOut])
def list_for_account(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("quotations.read")), db: Session = Depends(get_session)
) -> list[QuotationSummaryOut]:
    return [_summary(db, q) for q in quotations.list_for_account(db, auth.access, account_id)]


@router.post("/quotations", response_model=QuotationOut, status_code=201)
def create(
    body: CreateIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(
        db, quotations.create(db, auth.actor, auth.access, body.account_id, body.opportunity_id, body.customer_note)
    )


@router.get("/quotations/{quote_id}", response_model=QuotationOut)
def get(
    quote_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(db, quotations.get(db, auth.access, quote_id))


@router.patch("/quotations/{quote_id}", response_model=QuotationOut)
def update(
    quote_id: uuid.UUID, body: UpdateIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    view = quotations.update_draft(
        db,
        auth.actor,
        auth.access,
        quote_id,
        valid_until=body.valid_until,
        customer_note=body.customer_note,
        internal_note=body.internal_note,
        discount_reason=body.discount_reason,
    )
    return _out(db, view)


@router.post("/quotations/{quote_id}/lines", response_model=QuotationOut, status_code=201)
def add_line(
    quote_id: uuid.UUID, body: LineIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    view = quotations.add_line(
        db,
        auth.actor,
        auth.access,
        quote_id,
        body.entry_id,
        student_id=body.student_id,
        promotion_code=body.promotion_code,
        discount_minor=body.discount_minor,
    )
    return _out(db, view)


@router.delete("/quotations/{quote_id}/lines/{line_id}", response_model=QuotationOut)
def remove_line(
    quote_id: uuid.UUID,
    line_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> QuotationOut:
    return _out(db, quotations.remove_line(db, auth.actor, auth.access, quote_id, line_id))


@router.post("/quotations/{quote_id}/submit", response_model=QuotationOut)
def submit(
    quote_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(db, quotations.submit(db, auth.actor, auth.access, quote_id))


@router.post("/quotations/{quote_id}/approve", response_model=QuotationOut)
def approve(
    quote_id: uuid.UUID, body: ApproveIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    view = quotations.approve(
        db, auth.actor, auth.access, quote_id, body.capacity, valid_until=body.valid_until, comment=body.comment
    )
    return _out(db, view)


@router.post("/quotations/{quote_id}/send-back", response_model=QuotationOut)
def send_back(
    quote_id: uuid.UUID, body: ReasonIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(db, quotations.send_back(db, auth.actor, auth.access, quote_id, body.reason))


@router.post("/quotations/{quote_id}/issue", response_model=QuotationOut)
def issue(
    quote_id: uuid.UUID, body: IssueIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(db, quotations.issue(db, auth.actor, auth.access, quote_id, body.contact_id))


@router.post("/quotations/{quote_id}/outcome", response_model=QuotationOut)
def outcome(
    quote_id: uuid.UUID, body: OutcomeIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    view = quotations.record_outcome(
        db,
        auth.actor,
        auth.access,
        quote_id,
        body.outcome,
        body.note,
        price_change_reconfirmed=body.price_change_reconfirmed,
    )
    return _out(db, view)


@router.post("/quotations/{quote_id}/cancel", response_model=QuotationOut)
def cancel(
    quote_id: uuid.UUID, body: ReasonIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> QuotationOut:
    return _out(db, quotations.cancel(db, auth.actor, auth.access, quote_id, body.reason))


@router.post("/quotations/{quote_id}/revise", response_model=RevisionOut, status_code=201)
def revise(
    quote_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> RevisionOut:
    view, dropped = quotations.revise(db, auth.actor, auth.access, quote_id)
    return RevisionOut(quotation=_out(db, view), dropped=dropped)


@router.get("/quotations/{quote_id}/pdf", response_class=Response)
def quotation_pdf(
    quote_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> Response:
    view = quotations.get(db, auth.access, quote_id)
    q = view.quote
    if q.pricing_snapshot is None or q.snapshot_hash is None:
        raise Conflict("NOT_APPROVED", "A PDF exists only once the quotation is approved.")
    recipient = crm.contact_summary(db, q.issued_to_contact_id) if q.issued_to_contact_id else None
    content = pdf.render(q.pricing_snapshot, q.snapshot_hash, recipient.name if recipient else None)
    filename = f"{q.quote_number}-rev{q.revision_no}.pdf"
    return Response(
        content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
