"""Pricing API: catalogue (internal), lifecycle, activation checklist, corrections, tier selection and
the options a customer may be offered (docs/04)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, current_auth, require
from mixt.core.db import get_session
from mixt.core.errors import ValidationFailed
from mixt.core.money import Money, MoneyError, format_money, parse_major
from mixt.modules.crm import service as crm
from mixt.modules.pricing import resolution
from mixt.modules.pricing import service as pricing
from mixt.modules.reference import service as reference
from mixt.modules.settings import service as settings

router = APIRouter(tags=["pricing"])


# ------------------------------------------------------------------------------------ schemas


class AssignmentOut(BaseModel):
    id: uuid.UUID
    market_id: uuid.UUID
    market_name: str
    country_code: str
    status: str
    decision_ref: str | None
    requires_relationship_confirmation: bool
    relationship_confirmed_ref: str | None
    notes: str | None
    eligibility_rule_id: uuid.UUID | None = None
    minimum_purchase_rule_id: uuid.UUID | None = None


class VersionSummaryOut(BaseModel):
    id: uuid.UUID
    version_no: int
    status: str
    status_reason: str | None
    change_type: str
    supersedes_version_id: uuid.UUID | None
    figures_confirmation: str
    tax_treatment: str
    source_document: str
    source_received_on: date
    change_summary: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime


class BookOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    currency_code: str
    plan_type: str
    tier_label: str | None
    unit_type: str
    audience: str
    active_version_no: int | None
    latest_version: VersionSummaryOut
    assignments: list[AssignmentOut]


class BookDetailOut(BookOut):
    versions: list[VersionSummaryOut]


class EntryOut(BaseModel):
    id: uuid.UUID
    package_code: str
    display_name: str
    quantity: Decimal
    package_total_minor: int
    package_total_display: str
    advertised_unit_rate_minor: int | None
    derived_unit_rate_minor: int
    derived_unit_rate_display: str


class BenefitOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    customer_facing_text: str
    status: str


class GateCheckOut(BaseModel):
    code: str
    title: str
    ok: bool
    detail: str
    questions: list[str]


class VersionDetailOut(VersionSummaryOut):
    price_book_id: uuid.UUID
    price_book_code: str
    currency_code: str
    unit_type: str
    session_minutes_per_unit: int
    unit_definition_ref: str | None
    figures_locked: bool
    figures_confirmation_ref: str | None
    tax_treatment_ref: str | None
    approvals: int
    content_hash: str | None
    entries: list[EntryOut]
    benefits: list[BenefitOut]
    gate: list[GateCheckOut]
    gate_passes: bool


class CorrectionOut(BaseModel):
    version: VersionDetailOut
    anomalies: list[str]


class MarketPricingOut(BaseModel):
    market_id: uuid.UUID
    name: str
    country_code: str
    books: list[str]
    active_books: list[str]


class PricingStatusOut(BaseModel):
    catalogue_complete: bool
    books: int
    active_versions: int
    markets: list[MarketPricingOut]


class BenefitDefinitionOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    supplied_scope: str
    attached_to_versions: int


class ConfirmFiguresIn(BaseModel):
    decision_ref: str = Field(max_length=16)
    note: str = Field(max_length=2000)


class TaxIn(BaseModel):
    treatment: Literal["inclusive", "exclusive", "not_applicable"]
    decision_ref: str = Field(max_length=16)


class ReasonIn(BaseModel):
    reason: str = Field(max_length=2000)


class DecisionIn(BaseModel):
    decision_ref: str = Field(max_length=16)


class AssignIn(BaseModel):
    market_id: uuid.UUID
    decision_ref: str = Field(max_length=16)
    note: str = Field(default="", max_length=2000)


class CorrectionEntryIn(BaseModel):
    package_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,15}$")
    display_name: str = Field(min_length=1, max_length=60)
    quantity: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    package_total: str = Field(description="In major units exactly as on the sheet, e.g. '1170' or '285.00'")
    advertised_unit_rate: str | None = None


class CorrectionIn(BaseModel):
    source_document: str = Field(max_length=500)
    source_received_on: date
    change_summary: str = Field(max_length=2000)
    entries: list[CorrectionEntryIn] = Field(min_length=1, max_length=60)


class TierBookOut(BaseModel):
    price_book_id: uuid.UUID
    code: str
    tier_label: str | None
    has_active_pricing: bool


class TierSelectionOut(BaseModel):
    id: uuid.UUID
    price_book_id: uuid.UUID
    price_book_code: str
    tier_label: str | None
    plan_type: str
    market_name: str
    opportunity_id: uuid.UUID | None
    reason: str
    status: str
    selected_by_user_id: uuid.UUID
    selected_at: datetime


class TierChoiceOut(BaseModel):
    plan_type: str
    books: list[TierBookOut]
    current: TierSelectionOut | None


class TierChoicesOut(BaseModel):
    market_confirmed: bool
    choices: list[TierChoiceOut]
    history: list[TierSelectionOut]


class SelectTierIn(BaseModel):
    price_book_id: uuid.UUID
    reason: str = Field(max_length=2000)
    opportunity_id: uuid.UUID | None = None


class OfferOut(BaseModel):
    """A promotion shown next to the list price, never folded into it (ADR-15)."""

    code: str
    name: str
    kind: str
    description: str
    terms: str | None
    promotional_total_minor: int | None
    promotional_total_display: str | None
    bonus_units: Decimal | None
    ends_at: datetime
    stackable: bool


class OptionOut(BaseModel):
    option_ref: str
    entry_id: uuid.UUID
    price_book_code: str
    version_no: int
    package_code: str
    display_name: str
    quantity: Decimal
    unit_type: str
    minutes_per_unit: int
    package_total_minor: int
    currency: str
    package_total_display: str
    advertised_unit_rate_minor: int | None
    derived_unit_rate_display: str
    plan_type: str
    tier_label: str | None
    benefits: list[str]
    is_special: bool
    promotions: list[OfferOut]


class OptionsOut(BaseModel):
    market_country: str
    at: datetime
    options: list[OptionOut]


# ------------------------------------------------------------------------------------ helpers


def _summary(v: pricing.Version) -> VersionSummaryOut:
    return VersionSummaryOut(
        id=v.id,
        version_no=v.version_no,
        status=v.status,
        status_reason=v.status_reason,
        change_type=v.change_type,
        supersedes_version_id=v.supersedes_version_id,
        figures_confirmation=v.figures_confirmation,
        tax_treatment=v.tax_treatment,
        source_document=v.source_document,
        source_received_on=v.source_received_on,
        change_summary=v.change_summary,
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        created_at=v.created_at,
    )


def _book(view: pricing.BookView) -> BookOut:
    active = view.active_version
    return BookOut(
        id=view.book.id,
        code=view.book.code,
        name=view.book.name,
        currency_code=view.book.currency_code,
        plan_type=view.book.plan_type,
        tier_label=view.book.tier_label,
        unit_type=view.book.unit_type,
        audience=view.book.audience,
        active_version_no=active.version_no if active else None,
        latest_version=_summary(view.latest_version),
        assignments=[
            AssignmentOut(
                id=a.id,
                market_id=a.market_id,
                market_name=name,
                country_code=country,
                status=a.assignment_status,
                decision_ref=a.decision_ref,
                requires_relationship_confirmation=a.requires_relationship_confirmation,
                relationship_confirmed_ref=a.relationship_confirmed_ref,
                notes=a.notes,
                eligibility_rule_id=a.eligibility_rule_id,
                minimum_purchase_rule_id=a.minimum_purchase_rule_id,
            )
            for a, name, country in view.assignments
        ],
    )


def _money(db: Session, amount_minor: int, currency_code: str) -> str:
    currency = reference.currency(db, currency_code)
    return format_money(Money(amount_minor, currency_code), currency.minor_units)


def _version(db: Session, view: pricing.VersionView) -> VersionDetailOut:
    v, book = view.version, view.book
    return VersionDetailOut(
        **_summary(v).model_dump(),
        price_book_id=book.id,
        price_book_code=book.code,
        currency_code=book.currency_code,
        unit_type=book.unit_type,
        session_minutes_per_unit=v.session_minutes_per_unit,
        unit_definition_ref=v.unit_definition_ref,
        figures_locked=v.figures_locked,
        figures_confirmation_ref=v.figures_confirmation_ref,
        tax_treatment_ref=v.tax_treatment_ref,
        approvals=sum(1 for p in (v.approved_by, v.second_approved_by) if p is not None),
        content_hash=v.content_hash,
        entries=[
            EntryOut(
                id=e.id,
                package_code=e.package_code,
                display_name=e.display_name,
                quantity=Decimal(e.quantity),
                package_total_minor=e.package_total_minor,
                package_total_display=_money(db, e.package_total_minor, book.currency_code),
                advertised_unit_rate_minor=e.advertised_unit_rate_minor,
                derived_unit_rate_minor=e.derived_unit_rate_minor,
                derived_unit_rate_display=_money(db, e.derived_unit_rate_minor, book.currency_code)
                + f" per {book.unit_type} (derived)",
            )
            for e in view.entries
        ],
        benefits=[
            BenefitOut(
                id=b.id,
                code=d.code,
                name=d.name,
                kind=d.kind,
                customer_facing_text=b.customer_facing_text,
                status=b.status,
            )
            for b, d in view.benefits
        ],
        gate=[
            GateCheckOut(code=c.code, title=c.title, ok=c.ok, detail=c.detail, questions=list(c.questions))
            for c in view.gate
        ],
        gate_passes=view.gate_passes,
    )


def _selection(view: pricing.TierSelectionView) -> TierSelectionOut:
    s = view.selection
    return TierSelectionOut(
        id=s.id,
        price_book_id=s.price_book_id,
        price_book_code=view.book_code,
        tier_label=view.tier_label,
        plan_type=s.plan_type,
        market_name=view.market_name,
        opportunity_id=s.opportunity_id,
        reason=s.reason,
        status=s.status,
        selected_by_user_id=s.selected_by_user_id,
        selected_at=s.selected_at,
    )


def _parse_major(value: str, currency_code: str, minor_units: int) -> int:
    try:
        return parse_major(value, currency_code, minor_units).amount_minor
    except MoneyError as exc:
        raise ValidationFailed("INVALID_AMOUNT", f"{value!r}: {exc}") from exc


# ------------------------------------------------------------------------------------ catalogue


@router.get("/pricing/status", response_model=PricingStatusOut)
def pricing_status(
    auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> PricingStatusOut:
    books = pricing.list_books(db, auth.access)
    per_market: dict[uuid.UUID, MarketPricingOut] = {
        m.id: MarketPricingOut(market_id=m.id, name=m.name, country_code=m.country_code, books=[], active_books=[])
        for m in reference.list_markets(db)
    }
    for view in books:
        for assignment, _name, _country in view.assignments:
            if assignment.assignment_status == "confirmed" and assignment.market_id in per_market:
                per_market[assignment.market_id].books.append(view.book.code)
                if view.active_version is not None:
                    per_market[assignment.market_id].active_books.append(view.book.code)
    return PricingStatusOut(
        catalogue_complete=bool(settings.get_value(db, "pricing.catalogue_complete")),
        books=len(books),
        active_versions=sum(1 for v in books if v.active_version is not None),
        markets=sorted(per_market.values(), key=lambda m: m.name),
    )


@router.get("/pricing/books", response_model=list[BookOut])
def list_books(
    auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> list[BookOut]:
    return [_book(v) for v in pricing.list_books(db, auth.access)]


@router.get("/pricing/books/{book_id}", response_model=BookDetailOut)
def get_book(
    book_id: uuid.UUID, auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> BookDetailOut:
    view = pricing.get_book(db, auth.access, book_id)
    return BookDetailOut(**_book(view).model_dump(), versions=[_summary(v) for v in view.versions])


@router.get("/pricing/versions/{version_id}", response_model=VersionDetailOut)
def get_version(
    version_id: uuid.UUID, auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.view_version(db, auth.access, version_id))


@router.get("/pricing/benefit-definitions", response_model=list[BenefitDefinitionOut])
def benefit_definitions(
    auth: AuthContext = Depends(require("pricing.read")), db: Session = Depends(get_session)
) -> list[BenefitDefinitionOut]:
    return [
        BenefitDefinitionOut(
            id=d.id, code=d.code, name=d.name, kind=d.kind, supplied_scope=d.supplied_scope, attached_to_versions=n
        )
        for d, n in pricing.benefit_definitions(db, auth.access)
    ]


# ------------------------------------------------------------------------------------ lifecycle


@router.post("/pricing/versions/{version_id}/confirm-figures", response_model=VersionDetailOut)
def confirm_figures(
    version_id: uuid.UUID,
    body: ConfirmFiguresIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> VersionDetailOut:
    return _version(db, pricing.confirm_figures(db, auth.actor, auth.access, version_id, body.decision_ref, body.note))


@router.post("/pricing/versions/{version_id}/unit", response_model=VersionDetailOut)
def confirm_unit(
    version_id: uuid.UUID,
    body: DecisionIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> VersionDetailOut:
    return _version(db, pricing.confirm_unit_definition(db, auth.actor, auth.access, version_id, body.decision_ref))


@router.post("/pricing/versions/{version_id}/tax", response_model=VersionDetailOut)
def set_tax(
    version_id: uuid.UUID, body: TaxIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(
        db, pricing.set_tax_treatment(db, auth.actor, auth.access, version_id, body.treatment, body.decision_ref)
    )


@router.post("/pricing/versions/{version_id}/submit", response_model=VersionDetailOut)
def submit(
    version_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.submit(db, auth.actor, auth.access, version_id))


@router.post("/pricing/versions/{version_id}/approve", response_model=VersionDetailOut)
def approve(
    version_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.approve(db, auth.actor, auth.access, version_id))


@router.post("/pricing/versions/{version_id}/return", response_model=VersionDetailOut)
def return_to_draft(
    version_id: uuid.UUID, body: ReasonIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.return_to_draft(db, auth.actor, auth.access, version_id, body.reason))


@router.post("/pricing/versions/{version_id}/reject", response_model=VersionDetailOut)
def reject(
    version_id: uuid.UUID, body: ReasonIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.reject(db, auth.actor, auth.access, version_id, body.reason))


@router.post("/pricing/versions/{version_id}/activate", response_model=VersionDetailOut)
def activate(
    version_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.activate(db, auth.actor, auth.access, version_id))


@router.post("/pricing/versions/{version_id}/retire", response_model=VersionDetailOut)
def retire(
    version_id: uuid.UUID, body: ReasonIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> VersionDetailOut:
    return _version(db, pricing.retire(db, auth.actor, auth.access, version_id, body.reason))


@router.post("/pricing/versions/{version_id}/corrections", response_model=CorrectionOut, status_code=201)
def create_correction(
    version_id: uuid.UUID,
    body: CorrectionIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> CorrectionOut:
    original = pricing.view_version(db, auth.access, version_id)
    currency = reference.currency(db, original.book.currency_code)
    entries = [
        pricing.NewEntry(
            package_code=e.package_code,
            display_name=e.display_name,
            quantity=e.quantity,
            package_total_minor=_parse_major(e.package_total, currency.code, currency.minor_units),
            advertised_unit_rate_minor=_parse_major(e.advertised_unit_rate, currency.code, currency.minor_units)
            if e.advertised_unit_rate
            else None,
        )
        for e in body.entries
    ]
    view, notes = pricing.create_correction(
        db,
        auth.actor,
        auth.access,
        version_id,
        entries,
        body.source_document,
        body.source_received_on,
        body.change_summary,
    )
    return CorrectionOut(version=_version(db, view), anomalies=notes)


@router.post("/pricing/books/{book_id}/assignments", response_model=AssignmentOut, status_code=201)
def assign_market(
    book_id: uuid.UUID, body: AssignIn, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> AssignmentOut:
    row = pricing.assign_market(db, auth.actor, auth.access, book_id, body.market_id, body.decision_ref, body.note)
    market = reference.require_market(db, row.market_id)
    return _assignment_out(row, market.name, market.country_code)


def _assignment_out(row: pricing.Assignment, name: str, country: str) -> AssignmentOut:
    return AssignmentOut(
        id=row.id,
        market_id=row.market_id,
        market_name=name,
        country_code=country,
        status=row.assignment_status,
        decision_ref=row.decision_ref,
        requires_relationship_confirmation=row.requires_relationship_confirmation,
        relationship_confirmed_ref=row.relationship_confirmed_ref,
        notes=row.notes,
        eligibility_rule_id=row.eligibility_rule_id,
        minimum_purchase_rule_id=row.minimum_purchase_rule_id,
    )


@router.post("/pricing/assignments/{assignment_id}/revoke", response_model=AssignmentOut)
def revoke_assignment(
    assignment_id: uuid.UUID,
    body: ReasonIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> AssignmentOut:
    row = pricing.revoke_assignment(db, auth.actor, auth.access, assignment_id, body.reason)
    market = reference.require_market(db, row.market_id)
    return _assignment_out(row, market.name, market.country_code)


@router.post("/pricing/assignments/{assignment_id}/confirm-relationship", response_model=AssignmentOut)
def confirm_relationship(
    assignment_id: uuid.UUID,
    body: DecisionIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> AssignmentOut:
    row = pricing.confirm_relationship(db, auth.actor, auth.access, assignment_id, body.decision_ref)
    market = reference.require_market(db, row.market_id)
    return _assignment_out(row, market.name, market.country_code)


@router.post("/pricing/benefits/{benefit_id}/approve", status_code=204)
def approve_benefit(
    benefit_id: uuid.UUID, auth: AuthContext = Depends(current_auth), db: Session = Depends(get_session)
) -> None:
    pricing.approve_benefit(db, auth.actor, auth.access, benefit_id)


# ------------------------------------------------------------------------------------ customers


@router.get("/accounts/{account_id}/pricing/tiers", response_model=TierChoicesOut)
def tier_choices(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> TierChoicesOut:
    account = crm.get_account(db, auth.access, account_id)
    history = pricing.list_tier_selections(db, auth.access, account_id)
    if account.market_id is None or account.market_confirmed_at is None:
        return TierChoicesOut(market_confirmed=False, choices=[], history=[_selection(h) for h in history])
    active_books = pricing.books_with_active_version(db)
    choices = []
    for plan, books in pricing.tier_choices(db, account.market_id).items():
        current = next(
            (
                h
                for h in history
                if h.selection.status == "active"
                and h.selection.plan_type == plan
                and h.selection.opportunity_id is None
            ),
            None,
        )
        choices.append(
            TierChoiceOut(
                plan_type=plan,
                books=[
                    TierBookOut(
                        price_book_id=b.id,
                        code=b.code,
                        tier_label=b.tier_label,
                        has_active_pricing=b.id in active_books,
                    )
                    for b in books
                ],
                current=_selection(current) if current else None,
            )
        )
    return TierChoicesOut(market_confirmed=True, choices=choices, history=[_selection(h) for h in history])


@router.post("/accounts/{account_id}/pricing/tiers", response_model=TierSelectionOut, status_code=201)
def select_tier(
    account_id: uuid.UUID,
    body: SelectTierIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> TierSelectionOut:
    view = pricing.select_tier(
        db, auth.actor, auth.access, account_id, body.price_book_id, body.reason, body.opportunity_id
    )
    return _selection(view)


@router.post("/pricing/tier-selections/{selection_id}/revoke", response_model=TierSelectionOut)
def revoke_tier(
    selection_id: uuid.UUID,
    body: ReasonIn,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> TierSelectionOut:
    return _selection(pricing.revoke_tier_selection(db, auth.actor, auth.access, selection_id, body.reason))


@router.get("/accounts/{account_id}/pricing/options", response_model=OptionsOut)
def options(
    account_id: uuid.UUID,
    plan_type: Literal["standard", "premium"] | None = None,
    quantity: Decimal | None = None,
    opportunity_id: uuid.UUID | None = None,
    auth: AuthContext = Depends(current_auth),
    db: Session = Depends(get_session),
) -> OptionsOut:
    auth.access.require_somewhere("pricing.options.read")
    account = crm.get_account(db, auth.access, account_id)
    if account.market_id is not None:
        auth.access.require("pricing.options.read", account.market_id)
    sees_special = auth.access.has("pricing.special.view", account.market_id) if account.market_id else False
    found = resolution.resolve_options(
        db,
        account.id,
        plan_type=plan_type,
        quantity=quantity,
        opportunity_id=opportunity_id,
        include_special=sees_special,
    )
    return OptionsOut(
        market_country=found.market_country,
        at=found.at,
        options=[
            OptionOut(
                option_ref=o.option_ref,
                entry_id=o.entry_id,
                price_book_code=o.price_book_code,
                version_no=o.version_no,
                package_code=o.package_code,
                display_name=o.display_name,
                quantity=o.quantity,
                unit_type=o.unit_type,
                minutes_per_unit=o.minutes_per_unit,
                package_total_minor=o.package_total_minor,
                currency=o.currency,
                package_total_display=o.package_total_display,
                advertised_unit_rate_minor=o.advertised_unit_rate_minor,
                derived_unit_rate_display=o.derived_unit_rate_display,
                plan_type=o.plan_type,
                tier_label=o.tier_label,
                benefits=list(o.benefits),
                is_special=o.special_assignment_id is not None,
                promotions=[
                    OfferOut(
                        code=p.code,
                        name=p.name,
                        kind=p.kind,
                        description=p.description,
                        terms=p.terms,
                        promotional_total_minor=p.promotional_total_minor,
                        promotional_total_display=_money(db, p.promotional_total_minor, o.currency)
                        if p.promotional_total_minor is not None
                        else None,
                        bonus_units=p.bonus_units,
                        ends_at=p.ends_at,
                        stackable=p.stackable,
                    )
                    for p in o.promotions
                ],
            )
            for o in found.options
        ],
    )
