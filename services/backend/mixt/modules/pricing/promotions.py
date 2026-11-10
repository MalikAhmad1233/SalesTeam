"""Promotions (docs/04 §9, BD-021, ADR-15): kept apart from standard pricing.

* A promotion never changes a price-book entry, version or benefit. It is its own record and is shown
  next to the list price as a separate offer, never folded into it.
* Every promotion has an end date; expired promotions are never offered.
* Activation needs the global switch ``promotions.enabled`` (false until Mixt confirms its first
  promotion, Q-PRC-05), an approval by someone other than the submitter, a decision reference, and
  live target versions.
* Percentage promotions also need percentage discounts to be allowed (``pricing.discounts.mode``) and
  must give whole minor units on every targeted package: there is no rounding rule yet (Q-PRC-12), so
  none is guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.pricing import rule_service
from mixt.modules.pricing.models import (
    PriceBook,
    PriceBookEntry,
    PriceBookMarketAssignment,
    PriceBookVersion,
    Promotion,
    PromotionTarget,
)
from mixt.modules.pricing.service import DECISION_REF
from mixt.modules.settings import service as settings

PromotionRow = Promotion


@dataclass(frozen=True)
class TargetIn:
    price_book_version_id: uuid.UUID
    price_book_entry_id: uuid.UUID | None = None
    market_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Offer:
    promotion_id: uuid.UUID
    code: str
    name: str
    kind: str
    description: str
    terms: str | None
    promotional_total_minor: int | None
    bonus_units: Decimal | None
    ends_at: datetime
    stackable: bool


def _percent(value: dict[str, Any]) -> Decimal:
    try:
        percent = Decimal(str(value.get("percent")))
    except InvalidOperation as exc:
        raise ValidationFailed("INVALID_PROMOTION_VALUE", "percent must be a number such as '10'.") from exc
    if not Decimal(0) < percent < Decimal(100):
        raise ValidationFailed("INVALID_PROMOTION_VALUE", "percent must be between 0 and 100.")
    return percent


@dataclass(frozen=True)
class PromotionState:
    status: str
    starts_at: datetime
    ends_at: datetime
    max_redemptions: int | None
    max_per_account: int


def state(db: Session, promotion_id: uuid.UUID) -> PromotionState | None:
    row = db.get(Promotion, promotion_id)
    if row is None:
        return None
    return PromotionState(row.status, row.starts_at, row.ends_at, row.max_redemptions, row.max_per_account)


def promotional_total(kind: str, value: dict[str, Any], list_total: int) -> int | None:
    """The promotional total for one package, exactly; None when the kind does not change the price."""
    if kind == "amount_off":
        return list_total - int(value["amount_minor"])
    if kind == "percent_off":
        exact = Decimal(list_total) * (Decimal(100) - _percent(value)) / Decimal(100)
        if exact != exact.to_integral_value():
            raise ValidationFailed(
                "ROUNDING_RULE_REQUIRED",
                "This percentage does not give a whole amount; Mixt has not set a rounding rule (Q-PRC-12).",
            )
        return int(exact)
    return None


def _validate_value(kind: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationFailed("INVALID_PROMOTION_VALUE", "The value must be an object.")
    if kind == "percent_off" and set(value) == {"percent"}:
        _percent(value)
        return {"percent": str(Decimal(str(value["percent"])))}
    if kind == "amount_off" and set(value) == {"amount_minor", "currency"}:
        amount = value["amount_minor"]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValidationFailed("INVALID_PROMOTION_VALUE", "amount_minor must be a positive whole number.")
        return {"amount_minor": amount, "currency": str(value["currency"])}
    if kind == "bonus_units" and set(value) == {"units"}:
        try:
            units = Decimal(str(value["units"]))
        except InvalidOperation as exc:
            raise ValidationFailed("INVALID_PROMOTION_VALUE", "units must be a number.") from exc
        if units <= 0:
            raise ValidationFailed("INVALID_PROMOTION_VALUE", "units must be positive.")
        return {"units": str(units)}
    shapes = {
        "percent_off": "{'percent': '10'}",
        "amount_off": "{'amount_minor': 5000, 'currency': 'GBP'}",
        "bonus_units": "{'units': 2}",
    }
    raise ValidationFailed("INVALID_PROMOTION_VALUE", f"For {kind} the value is {shapes.get(kind, 'not supported')}.")


def _targets(db: Session, promotion: Promotion) -> list[PromotionTarget]:
    return list(db.scalars(select(PromotionTarget).where(PromotionTarget.promotion_id == promotion.id)))


def _target_entries(db: Session, target: PromotionTarget) -> list[PriceBookEntry]:
    if target.price_book_entry_id is not None:
        entry = db.get(PriceBookEntry, target.price_book_entry_id)
        return [entry] if entry else []
    return list(
        db.scalars(select(PriceBookEntry).where(PriceBookEntry.price_book_version_id == target.price_book_version_id))
    )


def list_promotions(db: Session, access: Access) -> list[Promotion]:
    access.require_somewhere("pricing.read")
    return list(db.scalars(select(Promotion).order_by(Promotion.created_at.desc(), Promotion.code)))


def get(db: Session, promotion_id: uuid.UUID) -> Promotion:
    row = db.get(Promotion, promotion_id)
    if row is None:
        raise NotFound("PROMOTION_NOT_FOUND", "Promotion not found.")
    return row


def targets_of(db: Session, promotion_id: uuid.UUID) -> list[PromotionTarget]:
    return _targets(db, get(db, promotion_id))


def create(
    db: Session,
    actor: Actor,
    access: Access,
    *,
    code: str,
    name: str,
    description: str,
    terms: str | None,
    kind: str,
    value: Any,
    starts_at: datetime,
    ends_at: datetime,
    targets: list[TargetIn],
    eligibility_rule_id: uuid.UUID | None = None,
    stackable: bool = False,
    max_redemptions: int | None = None,
    max_per_account: int = 1,
    decision_ref: str | None = None,
) -> Promotion:
    access.require_somewhere("pricing.promotions.manage")
    if ends_at <= starts_at:
        raise ValidationFailed("END_BEFORE_START", "A promotion must end after it starts.")
    if ends_at <= now_utc():
        raise ValidationFailed("ALREADY_ENDED", "This promotion would already be over.")
    if not description.strip() or not name.strip():
        raise ValidationFailed("DESCRIPTION_REQUIRED", "Give a name and a customer-facing description.")
    if decision_ref and not DECISION_REF.match(decision_ref):
        raise ValidationFailed("DECISION_REF_INVALID", "A decision reference looks like 'BD-034'.")
    if not targets:
        raise ValidationFailed("TARGETS_REQUIRED", "Say which price-book versions or packages it applies to.")
    clean = _validate_value(kind, value)
    if eligibility_rule_id is not None:
        rule = rule_service.get_rule(db, eligibility_rule_id)
        if rule.status != "approved" or rule.kind != "eligibility":
            raise ValidationFailed("RULE_NOT_USABLE", "Use an approved eligibility rule.")
    currencies: set[str] = set()
    smallest: int | None = None
    for t in targets:
        version = db.get(PriceBookVersion, t.price_book_version_id)
        if version is None:
            raise NotFound("PRICE_BOOK_VERSION_NOT_FOUND", "A target version does not exist.")
        book = db.get(PriceBook, version.price_book_id)
        assert book is not None  # noqa: S101 (foreign key)
        if book.plan_type == "promotional":
            raise ValidationFailed("PROMOTIONAL_BOOK", "Target standard pricing; promotional books are separate.")
        currencies.add(book.currency_code)
        entries = list(db.scalars(select(PriceBookEntry).where(PriceBookEntry.price_book_version_id == version.id)))
        if t.price_book_entry_id is not None:
            entries = [e for e in entries if e.id == t.price_book_entry_id]
            if not entries:
                raise ValidationFailed("ENTRY_NOT_IN_VERSION", "A target package is not in that version.")
        if t.market_id is not None and not db.scalar(
            select(PriceBookMarketAssignment.id).where(
                PriceBookMarketAssignment.price_book_id == book.id,
                PriceBookMarketAssignment.market_id == t.market_id,
                PriceBookMarketAssignment.assignment_status == "confirmed",
            )
        ):
            raise ValidationFailed("MARKET_NOT_ASSIGNED", f"{book.code} is not sold in that market.")
        for e in entries:
            smallest = e.package_total_minor if smallest is None else min(smallest, e.package_total_minor)
    if kind == "amount_off":
        if currencies != {clean["currency"]}:
            raise ValidationFailed(
                "CURRENCY_MISMATCH", "An amount off must be in the same currency as every targeted package."
            )
        if smallest is not None and clean["amount_minor"] >= smallest:
            raise ValidationFailed("AMOUNT_TOO_LARGE", "The amount off must be less than every targeted package.")
    promotion = Promotion(
        code=code,
        name=name.strip(),
        description=description.strip(),
        terms=(terms or "").strip() or None,
        kind=kind,
        value=clean,
        eligibility_rule_id=eligibility_rule_id,
        stackable=stackable,
        starts_at=starts_at,
        ends_at=ends_at,
        max_redemptions=max_redemptions,
        max_per_account=max_per_account,
        decision_ref=decision_ref or None,
        created_by=actor.principal_id,
    )
    db.add(promotion)
    db.flush()
    for t in targets:
        db.add(
            PromotionTarget(
                promotion_id=promotion.id,
                price_book_version_id=t.price_book_version_id,
                price_book_entry_id=t.price_book_entry_id,
                market_id=t.market_id,
            )
        )
    db.flush()
    audit.record(db, actor, "promotion_created", "promotion", promotion.id, {"code": code, "kind": kind})
    return promotion


def submit(db: Session, actor: Actor, access: Access, promotion_id: uuid.UUID) -> Promotion:
    access.require_somewhere("pricing.promotions.manage")
    row = get(db, promotion_id)
    if row.status != "draft":
        raise Conflict("INVALID_TRANSITION", f"Only a draft can be submitted (it is {row.status}).")
    row.status, row.submitted_by = "in_review", actor.principal_id
    db.flush()
    audit.record(db, actor, "promotion_submitted", "promotion", row.id, {})
    return row


def approve(db: Session, actor: Actor, access: Access, promotion_id: uuid.UUID) -> Promotion:
    access.require_somewhere("pricing.promotions.approve")
    row = get(db, promotion_id)
    if row.status != "in_review":
        raise Conflict("INVALID_TRANSITION", f"Only a promotion in review can be approved (it is {row.status}).")
    if row.submitted_by == actor.principal_id:
        raise PermissionDenied("FOUR_EYES", "Someone other than the submitter must approve a promotion.")
    if not row.decision_ref:
        raise ValidationFailed(
            "DECISION_REF_REQUIRED", "A promotion is Mixt's decision (Q-PRC-05): it needs a decision-log reference."
        )
    row.status, row.approved_by, row.approved_at = "approved", actor.principal_id, now_utc()
    db.flush()
    audit.record(db, actor, "promotion_approved", "promotion", row.id, {"ref": row.decision_ref})
    return row


def activation_problems(db: Session, row: Promotion) -> list[str]:
    problems: list[str] = []
    if not settings.get_value(db, "promotions.enabled"):
        problems.append("Promotions are switched off (setting promotions.enabled, Q-PRC-05)")
    if row.ends_at <= now_utc():
        problems.append("The promotion has already ended")
    if row.kind == "percent_off" and settings.get_value(db, "pricing.discounts.mode") != "percent_allowed":
        problems.append("Percentage offers are not allowed yet (setting pricing.discounts.mode, Q-PRC-12)")
    for target in _targets(db, row):
        version = db.get(PriceBookVersion, target.price_book_version_id)
        if version is None or version.status != "active":
            problems.append("A targeted price-book version is not active")
        for entry in _target_entries(db, target):
            try:
                promotional_total(row.kind, row.value, entry.package_total_minor)
            except ValidationFailed as exc:
                problems.append(f"{entry.display_name}: {exc.detail}")
    return sorted(set(problems))


def activate(db: Session, actor: Actor, access: Access, promotion_id: uuid.UUID) -> Promotion:
    access.require_somewhere("pricing.promotions.approve")
    row = get(db, promotion_id)
    if row.status != "approved":
        raise Conflict("INVALID_TRANSITION", f"Only an approved promotion can be activated (it is {row.status}).")
    problems = activation_problems(db, row)
    if problems:
        raise Conflict("PROMOTION_CANNOT_START", "This promotion cannot be activated.", missing=problems)
    row.status, row.activated_by, row.activated_at = "active", actor.principal_id, now_utc()
    db.flush()
    audit.record(db, actor, "promotion_activated", "promotion", row.id, {})
    return row


def cancel(db: Session, actor: Actor, access: Access, promotion_id: uuid.UUID, reason: str) -> Promotion:
    access.require_somewhere("pricing.promotions.approve")
    row = get(db, promotion_id)
    if row.status in ("expired", "cancelled"):
        raise Conflict("INVALID_TRANSITION", f"This promotion is already {row.status}.")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    row.status, row.status_reason = "cancelled", reason.strip()
    db.flush()
    audit.record(db, actor, "promotion_cancelled", "promotion", row.id, {"reason": reason.strip()})
    return row


def expire_due(db: Session, at: datetime | None = None) -> int:
    """Close promotions whose end date has passed (run by the worker; resolution also checks dates)."""
    when = at or now_utc()
    result = db.execute(
        update(Promotion)
        .where(Promotion.status.in_(("approved", "active")), Promotion.ends_at <= when)
        .values(status="expired", status_reason="End date reached")
        .returning(Promotion.id)
    )
    return len(result.all())


def offers_for(
    db: Session,
    version_id: uuid.UUID,
    entry_id: uuid.UUID,
    market_id: uuid.UUID,
    list_total: int,
    facts: dict[str, Any],
    at: datetime,
) -> list[Offer]:
    """Active, in-date, eligible promotions for one package, as separate offers next to its list price."""
    rows = db.scalars(
        select(Promotion)
        .join(PromotionTarget, PromotionTarget.promotion_id == Promotion.id)
        .where(
            Promotion.status == "active",
            Promotion.starts_at <= at,
            Promotion.ends_at > at,
            PromotionTarget.price_book_version_id == version_id,
            or_(PromotionTarget.price_book_entry_id.is_(None), PromotionTarget.price_book_entry_id == entry_id),
            or_(PromotionTarget.market_id.is_(None), PromotionTarget.market_id == market_id),
        )
        .distinct()
        .order_by(Promotion.code)
    )
    offers: list[Offer] = []
    for row in rows:
        if row.eligibility_rule_id is not None:
            rule = rule_service.get_rule(db, row.eligibility_rule_id)
            if not rule_service.evaluate(rule, facts).result:
                continue
        offers.append(
            Offer(
                promotion_id=row.id,
                code=row.code,
                name=row.name,
                kind=row.kind,
                description=row.description,
                terms=row.terms,
                promotional_total_minor=promotional_total(row.kind, row.value, list_total),
                bonus_units=Decimal(row.value["units"]) if row.kind == "bonus_units" else None,
                ends_at=row.ends_at,
                stackable=row.stackable,
            )
        )
    return offers
