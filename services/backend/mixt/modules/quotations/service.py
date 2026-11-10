"""Quotations (docs/04 §12-§13).

* Lines come **only** from price resolution for this customer: the server re-resolves the options and
  copies the chosen one (book, version, entry, plan, tier, quantity, unit, total, benefits). A figure
  is never typed in.
* The list price, a promotion and a discount are separate amounts on each line (ADR-15).
* Approvals are by people, never the preparer. A discount needs a sales approval and a pricing
  approval unless the sales approver's discount authority covers it (``pricing.discount_authority``;
  empty = nobody approves a discount alone, Q-PRC-11). A quote at list price needs a second person
  while ``quotations.approval = second_person`` (Q-PRC-22).
* On final approval the quotation is frozen as a snapshot with a SHA-256 hash; the PDF is made from
  that snapshot only. Changes after that are new revisions.
* Checks V-01 to V-09 run at submission, approval and issue.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.money import Money, format_money
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access
from mixt.modules.identity.catalogue import ROLES
from mixt.modules.pipeline import service as pipeline
from mixt.modules.pricing import promotions, resolution, special
from mixt.modules.pricing import service as pricing
from mixt.modules.quotations.models import PromotionRedemption, Quotation, QuotationApproval, QuotationLine
from mixt.modules.reference import service as reference
from mixt.modules.settings import service as settings

OPEN = frozenset({"draft", "pending_approval", "approved", "issued"})
Quote = Quotation
Line = QuotationLine


# ------------------------------------------------------------------------------------ discount authority


def validate_discount_authority(db: Session, value: Any) -> None:
    """``{"sales_manager": {"max_percent": "10", "max_amount_minor": {"GBP": 5000}}}``; empty = nobody alone."""
    if not isinstance(value, dict):
        raise ValidationFailed("INVALID_SETTING_VALUE", "Discount authority is an object keyed by role.")
    for role, limits in value.items():
        if role not in ROLES:
            raise ValidationFailed("INVALID_SETTING_VALUE", f"Unknown role {role!r}.")
        if not isinstance(limits, dict) or not limits or set(limits) - {"max_percent", "max_amount_minor"}:
            raise ValidationFailed(
                "INVALID_SETTING_VALUE", f"{role}: give max_percent and/or max_amount_minor per currency."
            )
        if "max_percent" in limits:
            try:
                percent = Decimal(str(limits["max_percent"]))
            except ArithmeticError as exc:
                raise ValidationFailed("INVALID_SETTING_VALUE", f"{role}: max_percent must be a number.") from exc
            if not Decimal(0) < percent <= Decimal(100):
                raise ValidationFailed("INVALID_SETTING_VALUE", f"{role}: max_percent must be above 0 and at most 100.")
        amounts = limits.get("max_amount_minor", {})
        if not isinstance(amounts, dict) or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in amounts.values()
        ):
            raise ValidationFailed(
                "INVALID_SETTING_VALUE", f"{role}: max_amount_minor is {{currency: whole minor units}}."
            )


def authority_covers(db: Session, principal_id: uuid.UUID, quote: Quotation) -> bool:
    """Whether this person's discount authority alone covers the quotation's discount."""
    if quote.discount_total_minor == 0:
        return True
    authority = settings.get_value(db, "pricing.discount_authority") or {}
    if not authority or quote.subtotal_minor <= 0 or quote.currency_code is None:
        return False
    percent = Decimal(quote.discount_total_minor) * 100 / Decimal(quote.subtotal_minor)
    for role, market_id in identity.roles_of(db, principal_id):
        limits = authority.get(role)
        if not limits or (market_id is not None and market_id != quote.market_id):
            continue
        ok = True
        if "max_percent" in limits:
            ok = ok and percent <= Decimal(str(limits["max_percent"]))
        if "max_amount_minor" in limits:
            cap = limits["max_amount_minor"].get(quote.currency_code)
            ok = ok and cap is not None and quote.discount_total_minor <= cap
        if ok:
            return True
    return False


def register() -> None:
    settings.register_validator("pricing.discount_authority", validate_discount_authority)


# ------------------------------------------------------------------------------------ reading


@dataclass
class QuoteView:
    quote: Quotation
    lines: list[QuotationLine]
    approvals: list[QuotationApproval]
    checks: list[str]
    needs: dict[str, Any]


def _lines(db: Session, quote_id: uuid.UUID) -> list[QuotationLine]:
    return list(
        db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == quote_id).order_by(QuotationLine.line_no))
    )


def _approvals(db: Session, quote_id: uuid.UUID) -> list[QuotationApproval]:
    return list(
        db.scalars(
            select(QuotationApproval)
            .where(QuotationApproval.quotation_id == quote_id)
            .order_by(QuotationApproval.decided_at, QuotationApproval.id)
        )
    )


def _view(db: Session, quote: Quotation) -> QuoteView:
    lines = _lines(db, quote.id)
    stage = "issue" if quote.status == "approved" else "submit"
    checks = problems(db, quote, lines, stage) if quote.status in ("draft", "pending_approval", "approved") else []
    return QuoteView(quote, lines, _approvals(db, quote.id), checks, quote.required_approvals or {})


def _get(db: Session, quote_id: uuid.UUID) -> Quotation:
    quote = db.get(Quotation, quote_id)
    if quote is None:
        raise NotFound("QUOTATION_NOT_FOUND", "Quotation not found.")
    return quote


def _visible(db: Session, access: Access, quote: Quotation) -> None:
    """Customer's team, or a pricing approver looking at a discount waiting for them."""
    if crm.is_visible(db, access, quote.account_id) and access.has_somewhere("quotations.read"):
        return
    needs = quote.required_approvals or {}
    if (
        quote.status == "pending_approval"
        and needs.get("pricing")
        and access.has_somewhere("quotations.approve_discount")
    ):
        return
    raise NotFound("QUOTATION_NOT_FOUND", "Quotation not found.")


def get(db: Session, access: Access, quote_id: uuid.UUID) -> QuoteView:
    quote = _get(db, quote_id)
    _visible(db, access, quote)
    return _view(db, quote)


def list_for_account(db: Session, access: Access, account_id: uuid.UUID) -> list[Quotation]:
    access.require_somewhere("quotations.read")
    crm.get_account(db, access, account_id)
    return list(
        db.scalars(
            select(Quotation)
            .where(Quotation.account_id == account_id)
            .order_by(Quotation.quote_number.desc(), Quotation.revision_no.desc())
        )
    )


def approval_inbox(db: Session, access: Access) -> list[Quotation]:
    """Quotations waiting for an approval this person may give."""
    rows = db.scalars(select(Quotation).where(Quotation.status == "pending_approval").order_by(Quotation.submitted_at))
    result = []
    for quote in rows:
        needs = quote.required_approvals or {}
        given = {a.capacity for a in _approvals(db, quote.id) if a.decision == "approve"}
        sales = needs.get("sales") and "sales" not in given and access.has_somewhere("quotations.approve")
        pricing_needed = needs.get("pricing") and "pricing" not in given
        price = pricing_needed and access.has_somewhere("quotations.approve_discount")
        if price or (sales and crm.is_visible(db, access, quote.account_id)):
            result.append(quote)
    return result


# ------------------------------------------------------------------------------------ drafting


def _require_manage(db: Session, access: Access, quote: Quotation) -> None:
    account = crm.get_account(db, access, quote.account_id)
    access.require("quotations.manage", account.market_id)


def create(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    customer_note: str | None = None,
) -> QuoteView:
    account = crm.get_account(db, access, account_id)
    access.require("quotations.manage", account.market_id)
    if account.market_id is None or account.market_confirmed_at is None:
        raise ValidationFailed("MARKET_NOT_CONFIRMED", "Confirm the customer's pricing market first.")
    if pipeline.opportunity_account(db, opportunity_id) != account.id:
        raise ValidationFailed("OPPORTUNITY_NOT_IN_ACCOUNT", "Choose an opportunity of this customer.")
    number = int(db.execute(text("SELECT nextval('quotation_number_seq')")).scalar_one())
    quote = Quotation(
        quote_number=f"Q-{number:06d}",
        account_id=account.id,
        opportunity_id=opportunity_id,
        market_id=account.market_id,
        prepared_by=actor.principal_id,
        customer_note=(customer_note or "").strip() or None,
    )
    db.add(quote)
    db.flush()
    audit.record(db, actor, "quotation_created", "quotation", quote.id, {"number": quote.quote_number})
    return _view(db, quote)


def _draft(db: Session, access: Access, quote_id: uuid.UUID) -> Quotation:
    quote = _get(db, quote_id)
    _require_manage(db, access, quote)
    if quote.status != "draft":
        raise Conflict("QUOTATION_NOT_DRAFT", f"Only a draft can be changed (this one is {quote.status}).")
    return quote


def _recalculate(db: Session, quote: Quotation) -> None:
    lines = _lines(db, quote.id)
    quote.subtotal_minor = sum(line.list_total_minor for line in lines)
    quote.promotion_total_minor = sum(line.promotion_discount_minor for line in lines)
    quote.discount_total_minor = sum(line.discount_minor for line in lines)
    quote.total_minor = sum(line.final_total_minor for line in lines)
    quote.currency_code = lines[0].currency_code if lines else None
    db.flush()


def _offered(db: Session, access: Access, quote: Quotation, entry_id: uuid.UUID) -> resolution.Option:
    sees_special = access.has("pricing.special.view", quote.market_id)
    found = resolution.resolve_options(
        db, quote.account_id, opportunity_id=quote.opportunity_id, include_special=sees_special
    )
    for option in found.options:
        if option.entry_id == entry_id:
            return option
    raise ValidationFailed(
        "NOT_AN_OFFERED_OPTION", "That package is not one of the options this customer can be offered right now."
    )


def add_line(
    db: Session,
    actor: Actor,
    access: Access,
    quote_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    student_id: uuid.UUID | None = None,
    promotion_code: str | None = None,
    discount_minor: int = 0,
) -> QuoteView:
    quote = _draft(db, access, quote_id)
    option = _offered(db, access, quote, entry_id)
    if quote.currency_code is not None and option.currency != quote.currency_code:
        raise ValidationFailed("CURRENCY_MISMATCH", "All lines of a quotation are in one currency (V-03).")
    if student_id is not None and not crm.students_belong(db, quote.account_id, [student_id]):
        raise ValidationFailed("STUDENT_NOT_IN_ACCOUNT", "That student belongs to another customer.")
    if discount_minor < 0:
        raise ValidationFailed("INVALID_DISCOUNT", "A discount cannot be negative.")
    promotion = None
    if promotion_code:
        promotion = next((p for p in option.promotions if p.code == promotion_code), None)
        if promotion is None:
            raise ValidationFailed("PROMOTION_NOT_OFFERED", "That promotion is not available for this package.")
    promo_discount = (
        option.package_total_minor - promotion.promotional_total_minor
        if promotion is not None and promotion.promotional_total_minor is not None
        else 0
    )
    final = option.package_total_minor - promo_discount - discount_minor
    if final <= 0:
        raise ValidationFailed("INVALID_DISCOUNT", "The discount would leave nothing to pay.")
    next_no = (
        db.scalar(select(func.max(QuotationLine.line_no)).where(QuotationLine.quotation_id == quote.id)) or 0
    ) + 1
    line = QuotationLine(
        quotation_id=quote.id,
        line_no=next_no,
        student_id=student_id,
        price_book_id=option.price_book_id,
        price_book_code=option.price_book_code,
        price_book_version_id=option.version_id,
        price_book_version_no=option.version_no,
        price_book_entry_id=option.entry_id,
        package_code=option.package_code,
        display_name=option.display_name,
        plan_type=option.plan_type,
        tier_label=option.tier_label,
        quantity=option.quantity,
        unit_type=option.unit_type,
        session_minutes_per_unit=option.minutes_per_unit,
        currency_code=option.currency,
        list_total_minor=option.package_total_minor,
        promotion_id=promotion.promotion_id if promotion else None,
        promotion_snapshot={
            "code": promotion.code,
            "name": promotion.name,
            "kind": promotion.kind,
            "description": promotion.description,
            "terms": promotion.terms,
            "ends_at": promotion.ends_at.isoformat(),
        }
        if promotion
        else None,
        promotion_discount_minor=promo_discount,
        bonus_units=promotion.bonus_units if promotion else None,
        discount_minor=discount_minor,
        final_total_minor=final,
        special_assignment_id=option.special_assignment_id,
        tier_selection_id=option.tier_selection_id,
        benefits_snapshot=list(option.benefits),
    )
    db.add(line)
    db.flush()
    _recalculate(db, quote)
    audit.record(
        db,
        actor,
        "quotation_line_added",
        "quotation",
        quote.id,
        {"entry": str(entry_id), "promotion": promotion_code, "discount_minor": discount_minor},
    )
    return _view(db, quote)


def remove_line(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID, line_id: uuid.UUID) -> QuoteView:
    quote = _draft(db, access, quote_id)
    line = db.get(QuotationLine, line_id)
    if line is None or line.quotation_id != quote.id:
        raise NotFound("LINE_NOT_FOUND", "Line not found.")
    db.delete(line)
    db.flush()
    _recalculate(db, quote)
    audit.record(db, actor, "quotation_line_removed", "quotation", quote.id, {"line": line.line_no})
    return _view(db, quote)


def update_draft(
    db: Session,
    actor: Actor,
    access: Access,
    quote_id: uuid.UUID,
    *,
    valid_until: date | None,
    customer_note: str | None,
    internal_note: str | None,
    discount_reason: str | None,
) -> QuoteView:
    quote = _draft(db, access, quote_id)
    if valid_until is not None and valid_until < now_utc().date():
        raise ValidationFailed("VALIDITY_IN_PAST", "The quotation cannot expire in the past.")
    quote.valid_until = valid_until
    quote.customer_note = (customer_note or "").strip() or None
    quote.internal_note = (internal_note or "").strip() or None
    quote.discount_reason = (discount_reason or "").strip() or None
    db.flush()
    audit.record(db, actor, "quotation_updated", "quotation", quote.id, {})
    return _view(db, quote)


# ------------------------------------------------------------------------------------ checks (V-01 to V-09)


def problems(db: Session, quote: Quotation, lines: list[QuotationLine], stage: str) -> list[str]:
    """What stops this quotation going further. ``stage``: submit, approve or issue."""
    found: list[str] = []
    today = now_utc().date()
    if not lines:
        found.append("V-00 The quotation has no lines")
    account = crm.account_for_system(db, quote.account_id)
    if account.market_id != quote.market_id:
        found.append("V-04 The customer's pricing market has changed since this quotation was started")
    currencies = {line.currency_code for line in lines}
    if len(currencies) > 1:
        found.append("V-03 Lines are in more than one currency")
    specials = set()
    now = now_utc()
    for line in lines:
        facts = pricing.version_facts(db, line.price_book_version_id)
        if facts is None or facts.status != "active":
            found.append(f"V-01 {line.display_name}: price version {line.price_book_version_no} is no longer active")
        if pricing.entry_total(db, line.price_book_entry_id) != line.list_total_minor:
            found.append(f"V-02 {line.display_name}: list price differs from the price book")
        if line.final_total_minor != line.list_total_minor - line.promotion_discount_minor - line.discount_minor:
            found.append(f"V-02 {line.display_name}: totals do not add up")
        if line.special_assignment_id is not None:
            specials.add(line.special_assignment_id)
        if line.promotion_id is not None:
            promo = promotions.state(db, line.promotion_id)
            if promo is None or promo.status != "active" or not (promo.starts_at <= now < promo.ends_at):
                found.append(f"V-05 {line.display_name}: the promotion is no longer running")
                continue
            used = db.scalar(select(func.count()).where(PromotionRedemption.promotion_id == line.promotion_id)) or 0
            mine = (
                db.scalar(
                    select(func.count()).where(
                        PromotionRedemption.promotion_id == line.promotion_id,
                        PromotionRedemption.account_id == quote.account_id,
                    )
                )
                or 0
            )
            if promo.max_redemptions is not None and used >= promo.max_redemptions:
                found.append(f"V-05 {line.display_name}: the promotion has been fully used")
            if mine >= promo.max_per_account:
                found.append(f"V-05 {line.display_name}: this customer has already used the promotion")
    if any(special.assignment_status(db, a) != "active" for a in specials):
        found.append("V-04 The customer's special pricing is no longer active")
    if quote.discount_total_minor > 0 and not quote.discount_reason:
        found.append("V-06 Give a reason for the discount")
    if stage in ("approve", "issue"):
        if quote.valid_until is None:
            found.append("V-09 Set the date the quotation is valid until")
        elif quote.valid_until < today:
            found.append("V-09 The validity date has passed")
    if stage == "issue" and quote.snapshot_hash and quote.pricing_snapshot is not None:
        if _hash(quote.pricing_snapshot) != quote.snapshot_hash:
            found.append("V-07 The frozen quotation does not match its fingerprint")
        if _snapshot(db, quote, lines, include_approvals=False) != {
            k: v for k, v in quote.pricing_snapshot.items() if k not in ("approvals", "approved_at")
        }:
            found.append("V-07 The lines no longer match the frozen quotation")
    return found


# ------------------------------------------------------------------------------------ approvals


def _required(db: Session, quote: Quotation, lines: list[QuotationLine]) -> dict[str, Any]:
    reasons = []
    if quote.discount_total_minor > 0:
        reasons.append("discount")
    if any(line.promotion_id for line in lines):
        reasons.append("promotion")
    if any(line.special_assignment_id for line in lines):
        reasons.append("special_pricing")
    list_price_self = settings.get_value(db, "quotations.approval") == "preparer_may_issue_list_price"
    sales = bool(reasons) or not list_price_self
    return {"sales": sales, "pricing": quote.discount_total_minor > 0, "reasons": reasons or ["list_price"]}


def submit(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID) -> QuoteView:
    quote = _draft(db, access, quote_id)
    lines = _lines(db, quote.id)
    if settings.get_value(db, "quotations.validity").startswith("fixed_days:") and quote.valid_until is None:
        days = int(settings.get_value(db, "quotations.validity").split(":")[1])
        quote.valid_until = now_utc().date() + timedelta(days=days)
    found = problems(db, quote, lines, "submit")
    if found:
        raise Conflict("QUOTATION_NOT_READY", "This quotation cannot be submitted yet.", missing=found)
    quote.required_approvals = _required(db, quote, lines)
    quote.status, quote.submitted_at = "pending_approval", now_utc()
    db.flush()
    audit.record(db, actor, "quotation_submitted", "quotation", quote.id, {"needs": quote.required_approvals})
    if not quote.required_approvals["sales"] and not quote.required_approvals["pricing"]:
        return _finalise(db, actor, quote)
    return _view(db, quote)


def outstanding(db: Session, quote: Quotation) -> set[str]:
    needs = quote.required_approvals or {}
    given = {a.capacity: a for a in _approvals(db, quote.id) if a.decision == "approve"}
    outstanding = {c for c in ("sales", "pricing") if needs.get(c) and c not in given}
    if "pricing" in outstanding and "sales" in given:
        approver = identity.principal_of_user(db, given["sales"].decided_by_user_id)
        if approver is not None and authority_covers(db, approver, quote):
            outstanding.discard("pricing")
    return outstanding


def approve(
    db: Session,
    actor: Actor,
    access: Access,
    quote_id: uuid.UUID,
    capacity: str,
    *,
    valid_until: date | None = None,
    comment: str | None = None,
) -> QuoteView:
    if actor.kind != "user" or actor.user_id is None:
        raise PermissionDenied("PERSON_REQUIRED", "Only a person can approve a quotation.")
    quote = _get(db, quote_id)
    _visible(db, access, quote)
    if quote.status != "pending_approval":
        raise Conflict("INVALID_TRANSITION", f"This quotation is {quote.status}, not waiting for approval.")
    if capacity not in ("sales", "pricing"):
        raise ValidationFailed("INVALID_CAPACITY", "Approve as 'sales' or 'pricing'.")
    access.require_somewhere("quotations.approve" if capacity == "sales" else "quotations.approve_discount")
    if actor.principal_id == quote.prepared_by:
        raise PermissionDenied("FOUR_EYES", "Someone other than the person who prepared it must approve it.")
    if capacity not in outstanding(db, quote):
        raise Conflict("APPROVAL_NOT_NEEDED", f"No {capacity} approval is waiting on this quotation.")
    if any(a.decided_by_user_id == actor.user_id for a in _approvals(db, quote.id)):
        raise Conflict("ALREADY_DECIDED", "You have already approved this quotation; a different person must.")
    if valid_until is not None:
        if valid_until < now_utc().date():
            raise ValidationFailed("VALIDITY_IN_PAST", "The quotation cannot expire in the past.")
        quote.valid_until = valid_until
    found = problems(db, quote, _lines(db, quote.id), "approve")
    if found:
        raise Conflict("QUOTATION_NOT_READY", "This quotation cannot be approved.", missing=found)
    db.add(
        QuotationApproval(
            quotation_id=quote.id,
            decided_by_user_id=actor.user_id,
            capacity=capacity,
            decision="approve",
            comment=(comment or "").strip() or None,
        )
    )
    db.flush()
    audit.record(db, actor, "quotation_approved", "quotation", quote.id, {"capacity": capacity})
    if not outstanding(db, quote):
        return _finalise(db, actor, quote)
    return _view(db, quote)


def send_back(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID, reason: str) -> QuoteView:
    quote = _get(db, quote_id)
    _visible(db, access, quote)
    if not (access.has_somewhere("quotations.approve") or access.has_somewhere("quotations.approve_discount")):
        raise PermissionDenied("PERMISSION_DENIED", "Only approvers can send a quotation back.")
    if quote.status != "pending_approval":
        raise Conflict("INVALID_TRANSITION", f"This quotation is {quote.status}.")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Say what needs to change.")
    for approval in _approvals(db, quote.id):
        db.delete(approval)
    quote.status, quote.status_reason, quote.required_approvals = "draft", reason.strip(), None
    db.flush()
    audit.record(db, actor, "quotation_sent_back", "quotation", quote.id, {"reason": reason.strip()})
    return _view(db, quote)


# ------------------------------------------------------------------------------------ snapshot


def _hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _money(db: Session, amount: int, currency: str) -> str:
    return format_money(Money(amount, currency), reference.currency(db, currency).minor_units)


def _snapshot(
    db: Session, quote: Quotation, lines: list[QuotationLine], *, include_approvals: bool = True
) -> dict[str, Any]:
    account = crm.account_for_system(db, quote.account_id)
    market = reference.require_market(db, quote.market_id)
    currency = quote.currency_code or ""
    facts = [pricing.version_facts(db, line.price_book_version_id) for line in lines]
    taxes = {f.tax_treatment for f in facts if f is not None}
    snapshot: dict[str, Any] = {
        "quote_number": quote.quote_number,
        "revision_no": quote.revision_no,
        "customer": {"account_number": account.account_number, "name": account.display_name},
        "market": {"country": market.country_code, "name": market.name},
        "currency": currency,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "tax_treatment": sorted(t for t in taxes if t)[0] if len(taxes) == 1 else "mixed",
        "lines": [
            {
                "line_no": line.line_no,
                "price_book_code": line.price_book_code,
                "price_book_version_id": str(line.price_book_version_id),
                "price_book_version_no": line.price_book_version_no,
                "price_book_entry_id": str(line.price_book_entry_id),
                "package_code": line.package_code,
                "display_name": line.display_name,
                "plan_type": line.plan_type,
                "tier_label": line.tier_label,
                "quantity": str(Decimal(line.quantity).normalize()),
                "unit_type": line.unit_type,
                "minutes_per_unit": line.session_minutes_per_unit,
                "list_total_minor": line.list_total_minor,
                "list_total": _money(db, line.list_total_minor, line.currency_code),
                "promotion": line.promotion_snapshot,
                "promotion_discount_minor": line.promotion_discount_minor,
                "promotion_discount": _money(db, line.promotion_discount_minor, line.currency_code)
                if line.promotion_discount_minor
                else None,
                "bonus_units": str(Decimal(line.bonus_units).normalize()) if line.bonus_units is not None else None,
                "discount_minor": line.discount_minor,
                "discount": _money(db, line.discount_minor, line.currency_code) if line.discount_minor else None,
                "final_total_minor": line.final_total_minor,
                "final_total": _money(db, line.final_total_minor, line.currency_code),
                "special_pricing": line.special_assignment_id is not None,
                "benefits": list(line.benefits_snapshot),
            }
            for line in lines
        ],
        "totals": {
            "subtotal_minor": quote.subtotal_minor,
            "promotion_total_minor": quote.promotion_total_minor,
            "discount_total_minor": quote.discount_total_minor,
            "total_minor": quote.total_minor,
            "total": _money(db, quote.total_minor, currency) if currency else None,
        },
        "customer_note": quote.customer_note,
    }
    if include_approvals:
        snapshot["approvals"] = [
            {"capacity": a.capacity, "user_id": str(a.decided_by_user_id), "at": a.decided_at.isoformat()}
            for a in _approvals(db, quote.id)
            if a.decision == "approve"
        ]
        snapshot["approved_at"] = (quote.approved_at or now_utc()).isoformat()
    return snapshot


def _finalise(db: Session, actor: Actor, quote: Quotation) -> QuoteView:
    lines = _lines(db, quote.id)
    found = problems(db, quote, lines, "approve")
    if found:
        raise Conflict("QUOTATION_NOT_READY", "This quotation cannot be approved.", missing=found)
    quote.approved_at = now_utc()
    snapshot = _snapshot(db, quote, lines)
    quote.pricing_snapshot, quote.snapshot_hash = snapshot, _hash(snapshot)
    quote.tax_treatment = snapshot["tax_treatment"]
    quote.status = "approved"
    db.flush()
    audit.record(db, actor, "quotation_frozen", "quotation", quote.id, {"hash": quote.snapshot_hash})
    return _view(db, quote)


# ------------------------------------------------------------------------------------ issue and outcome


def issue(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID, contact_id: uuid.UUID) -> QuoteView:
    quote = _get(db, quote_id)
    _require_manage(db, access, quote)
    if quote.status != "approved":
        raise Conflict("INVALID_TRANSITION", f"Only an approved quotation can be issued (it is {quote.status}).")
    contact = crm.contact_summary(db, contact_id)
    found = problems(db, quote, _lines(db, quote.id), "issue")
    if contact is None or contact.account_id != quote.account_id:
        found.append("V-08 The recipient must be a contact of this customer")
    if found:
        raise Conflict("QUOTATION_NOT_READY", "This quotation cannot be issued.", missing=found)
    quote.status, quote.issued_at, quote.issued_by = "issued", now_utc(), actor.principal_id
    quote.issued_to_contact_id, quote.issued_via = contact_id, "manual"
    db.flush()
    total = quote.pricing_snapshot["totals"]["total"] if quote.pricing_snapshot else None
    audit.record(db, actor, "quotation_issued", "quotation", quote.id, {"to": str(contact_id)})
    events.emit(
        db,
        actor,
        "quotation.issued",
        "quotation",
        quote.id,
        {"number": f"{quote.quote_number} rev {quote.revision_no}", "total": total},
        quote.account_id,
    )
    return _view(db, quote)


def record_outcome(
    db: Session,
    actor: Actor,
    access: Access,
    quote_id: uuid.UUID,
    outcome: str,
    note: str,
    *,
    price_change_reconfirmed: bool = False,
) -> QuoteView:
    """Record the customer's answer (there is no customer portal yet: staff record it)."""
    quote = _get(db, quote_id)
    _require_manage(db, access, quote)
    if quote.status != "issued":
        raise Conflict("INVALID_TRANSITION", f"Only an issued quotation has an outcome (this one is {quote.status}).")
    if outcome not in ("accepted", "declined"):
        raise ValidationFailed("INVALID_OUTCOME", "Outcome is accepted or declined.")
    if len(note.strip()) < 3:
        raise ValidationFailed("NOTE_REQUIRED", "Say how the customer answered (e.g. 'confirmed by WhatsApp').")
    lines = _lines(db, quote.id)
    if outcome == "accepted":
        if quote.valid_until is not None and quote.valid_until < now_utc().date():
            quote.status, quote.status_reason = "expired", "Validity ended before acceptance"
            db.flush()
            raise Conflict("QUOTATION_EXPIRED", "This quotation expired before it was accepted; issue a revision.")
        changed = [line for line in lines if _version_status(db, line) != "active"]
        policy = settings.get_value(db, "quotations.on_price_change")
        if changed and policy == "expire_on_change":
            quote.status, quote.status_reason = "expired", "Price changed after issue"
            db.flush()
            raise Conflict("PRICE_CHANGED", "The price changed after this quotation was issued; issue a revision.")
        if changed and policy == "reconfirm_before_acceptance" and not price_change_reconfirmed:
            raise Conflict(
                "PRICE_CHANGE_RECONFIRM",
                "The price changed after this quotation was issued. A person must confirm it is still honoured.",
                missing=[
                    f"{line.display_name}: version {line.price_book_version_no} is no longer active" for line in changed
                ],
            )
        for line in lines:
            if line.promotion_id is not None:
                db.add(
                    PromotionRedemption(
                        promotion_id=line.promotion_id, account_id=quote.account_id, quotation_id=quote.id
                    )
                )
    quote.status, quote.outcome_at, quote.outcome_recorded_by = outcome, now_utc(), actor.principal_id
    quote.outcome_note = note.strip() + (" [price change reconfirmed]" if price_change_reconfirmed else "")
    db.flush()
    audit.record(db, actor, f"quotation_{outcome}", "quotation", quote.id, {"note": note.strip()})
    events.emit(
        db,
        actor,
        f"quotation.{outcome}",
        "quotation",
        quote.id,
        {"number": f"{quote.quote_number} rev {quote.revision_no}", "note": note.strip()},
        quote.account_id,
    )
    return _view(db, quote)


def _version_status(db: Session, line: QuotationLine) -> str | None:
    facts = pricing.version_facts(db, line.price_book_version_id)
    return facts.status if facts else None


def cancel(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID, reason: str) -> QuoteView:
    quote = _get(db, quote_id)
    _require_manage(db, access, quote)
    if quote.status not in OPEN:
        raise Conflict("INVALID_TRANSITION", f"This quotation is already {quote.status}.")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    quote.status, quote.status_reason = "cancelled", reason.strip()
    db.flush()
    audit.record(db, actor, "quotation_cancelled", "quotation", quote.id, {"reason": reason.strip()})
    return _view(db, quote)


def revise(db: Session, actor: Actor, access: Access, quote_id: uuid.UUID) -> tuple[QuoteView, list[str]]:
    """A new draft revision priced from today's options; the previous revision is superseded, never edited."""
    old = _get(db, quote_id)
    _require_manage(db, access, old)
    if old.status not in ("pending_approval", "approved", "issued", "expired"):
        raise Conflict("INVALID_TRANSITION", f"A {old.status} quotation cannot be revised.")
    revision_no = (
        db.scalar(select(func.max(Quotation.revision_no)).where(Quotation.quote_number == old.quote_number)) or 0
    ) + 1
    new = Quotation(
        quote_number=old.quote_number,
        revision_no=revision_no,
        parent_quotation_id=old.id,
        account_id=old.account_id,
        opportunity_id=old.opportunity_id,
        market_id=old.market_id,
        prepared_by=actor.principal_id,
        customer_note=old.customer_note,
        internal_note=old.internal_note,
        discount_reason=old.discount_reason,
    )
    db.add(new)
    if old.status != "expired":
        old.status, old.status_reason = "superseded", f"Replaced by revision {revision_no}"
    db.flush()
    dropped: list[str] = []
    for line in _lines(db, old.id):
        code = line.promotion_snapshot.get("code") if line.promotion_snapshot else None
        try:
            add_line(
                db,
                actor,
                access,
                new.id,
                line.price_book_entry_id,
                student_id=line.student_id,
                promotion_code=code,
                discount_minor=line.discount_minor,
            )
        except ValidationFailed as exc:
            dropped.append(f"{line.display_name}: {exc.detail}")
    audit.record(db, actor, "quotation_revised", "quotation", new.id, {"from": str(old.id), "dropped": dropped})
    return _view(db, new), dropped


def expire_due(db: Session, today: date | None = None) -> int:
    """Approved or issued quotations past their validity date expire (run by the worker)."""
    day = today or now_utc().date()
    rows = list(
        db.scalars(select(Quotation).where(Quotation.status.in_(("approved", "issued")), Quotation.valid_until < day))
    )
    for quote in rows:
        quote.status, quote.status_reason = "expired", "Validity date passed"
    db.flush()
    return len(rows)
