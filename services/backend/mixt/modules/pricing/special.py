"""Confidential customer pricing (docs/04 §7): a restricted price book for one customer, requested by one
person and approved by another. Never created by AI. Only people with ``pricing.special.view`` see it,
and it is offered only to that customer, in that customer's own market."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.identity.access import Access
from mixt.modules.pricing.models import CustomerPricingAssignment, PriceBook, PriceBookMarketAssignment

Special = CustomerPricingAssignment


@dataclass(frozen=True)
class SpecialView:
    assignment: CustomerPricingAssignment
    book_code: str
    book_name: str


def _view(db: Session, row: CustomerPricingAssignment) -> SpecialView:
    book = db.get(PriceBook, row.price_book_id)
    if book is None:  # pragma: no cover - foreign key
        raise NotFound("PRICE_BOOK_NOT_FOUND", "Price book not found.")
    return SpecialView(row, book.code, book.name)


def _expire_due(db: Session, account_id: uuid.UUID) -> None:
    db.execute(
        update(CustomerPricingAssignment)
        .where(
            CustomerPricingAssignment.account_id == account_id,
            CustomerPricingAssignment.status == "active",
            CustomerPricingAssignment.valid_to.is_not(None),
            CustomerPricingAssignment.valid_to <= now_utc(),
        )
        .values(status="expired", closed_at=now_utc(), close_reason="Validity ended")
    )


def list_for_account(db: Session, access: Access, account_id: uuid.UUID) -> list[SpecialView]:
    account = crm.get_account(db, access, account_id)
    access.require("pricing.special.view", account.market_id)
    _expire_due(db, account.id)
    rows = db.scalars(
        select(CustomerPricingAssignment)
        .where(CustomerPricingAssignment.account_id == account.id)
        .order_by(CustomerPricingAssignment.created_at.desc(), CustomerPricingAssignment.id.desc())
    )
    return [_view(db, r) for r in rows]


def restricted_books(db: Session, access: Access, account_id: uuid.UUID) -> list[PriceBook]:
    """Restricted books that could be granted to this customer: confirmed for the customer's own market."""
    account = crm.get_account(db, access, account_id)
    access.require("pricing.special.request", account.market_id)
    if account.market_id is None or account.market_confirmed_at is None:
        return []
    return list(
        db.scalars(
            select(PriceBook)
            .join(PriceBookMarketAssignment, PriceBookMarketAssignment.price_book_id == PriceBook.id)
            .where(
                PriceBook.audience == "restricted",
                PriceBook.archived_at.is_(None),
                PriceBookMarketAssignment.market_id == account.market_id,
                PriceBookMarketAssignment.assignment_status == "confirmed",
            )
            .order_by(PriceBook.code)
        )
    )


def request(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    price_book_id: uuid.UUID,
    reason: str,
    valid_from: datetime | None,
    valid_to: datetime | None,
) -> SpecialView:
    if actor.kind != "user" or actor.user_id is None:
        raise PermissionDenied("PERSON_REQUIRED", "Only a person can request special pricing.")
    account = crm.get_account(db, access, account_id)
    access.require("pricing.special.request", account.market_id)
    if account.market_id is None or account.market_confirmed_at is None:
        raise ValidationFailed("MARKET_NOT_CONFIRMED", "Confirm the customer's pricing market first.")
    if len(reason.strip()) < 10:
        raise ValidationFailed("REASON_REQUIRED", "Explain why this customer gets special pricing.")
    if price_book_id not in {b.id for b in restricted_books(db, access, account.id)}:
        raise ValidationFailed(
            "NOT_A_SPECIAL_BOOK",
            "Special pricing must be a restricted price book confirmed for this customer's market.",
        )
    start = valid_from or now_utc()
    if valid_to is not None and valid_to <= start:
        raise ValidationFailed("INVALID_DATES", "The end must be after the start.")
    row = CustomerPricingAssignment(
        account_id=account.id,
        price_book_id=price_book_id,
        reason=reason.strip(),
        valid_from=start,
        valid_to=valid_to,
        requested_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    audit.record(db, actor, "special_pricing_requested", "account", account.id, {"assignment": str(row.id)})
    return _view(db, row)


def _get(db: Session, access: Access, assignment_id: uuid.UUID) -> CustomerPricingAssignment:
    row = db.get(CustomerPricingAssignment, assignment_id)
    if row is None:
        raise NotFound("SPECIAL_PRICING_NOT_FOUND", "Special pricing not found.")
    account = crm.get_account(db, access, row.account_id)
    access.require("pricing.special.view", account.market_id)
    return row


def approve(db: Session, actor: Actor, access: Access, assignment_id: uuid.UUID) -> SpecialView:
    row = _get(db, access, assignment_id)
    account = crm.account_for_system(db, row.account_id)
    access.require("pricing.special.approve", account.market_id)
    if actor.kind != "user" or actor.user_id is None:
        raise PermissionDenied("PERSON_REQUIRED", "Only a person can approve special pricing.")
    if row.status != "pending_approval":
        raise Conflict("NOT_PENDING", f"This request is {row.status}.")
    if row.requested_by == actor.user_id:
        raise PermissionDenied("FOUR_EYES", "Someone other than the requester must approve special pricing.")
    row.status, row.approved_by, row.approved_at = "active", actor.user_id, now_utc()
    db.flush()
    audit.record(db, actor, "special_pricing_approved", "account", row.account_id, {"assignment": str(row.id)})
    return _view(db, row)


def close(db: Session, actor: Actor, access: Access, assignment_id: uuid.UUID, action: str, reason: str) -> SpecialView:
    """Reject a pending request or revoke an active one."""
    row = _get(db, access, assignment_id)
    account = crm.account_for_system(db, row.account_id)
    access.require("pricing.special.approve", account.market_id)
    expected = {"reject": "pending_approval", "revoke": "active"}
    if action not in expected:
        raise ValidationFailed("INVALID_ACTION", "Use reject or revoke.")
    if row.status != expected[action]:
        raise Conflict("INVALID_TRANSITION", f"Cannot {action} special pricing that is {row.status}.")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    row.status = "rejected" if action == "reject" else "revoked"
    row.closed_by, row.closed_at, row.close_reason = actor.principal_id, now_utc(), reason.strip()
    db.flush()
    audit.record(db, actor, f"special_pricing_{row.status}", "account", row.account_id, {"reason": reason.strip()})
    return _view(db, row)


def active_books(db: Session, account_id: uuid.UUID, at: datetime) -> dict[uuid.UUID, uuid.UUID]:
    """Restricted books this customer may be offered at ``at``: {price_book_id: assignment_id}."""
    rows = db.scalars(
        select(CustomerPricingAssignment).where(
            CustomerPricingAssignment.account_id == account_id,
            CustomerPricingAssignment.status == "active",
            CustomerPricingAssignment.valid_from <= at,
            or_(CustomerPricingAssignment.valid_to.is_(None), CustomerPricingAssignment.valid_to > at),
        )
    )
    return {r.price_book_id: r.id for r in rows}


def assignment_status(db: Session, assignment_id: uuid.UUID) -> str | None:
    row = db.get(CustomerPricingAssignment, assignment_id)
    return row.status if row else None
