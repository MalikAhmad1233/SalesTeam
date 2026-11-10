"""Price resolution (docs/04 §6): which package options may be offered to one customer, right now.

Deterministic: the same customer and database state always give the same options, in the same order.
It never converts currencies, never borrows another market's pricing, never picks a tier, and never
returns a draft, unapproved or expired version. When it cannot answer, it refuses with a stable error
code and a customer-safe message, and a person takes over.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mixt.core.errors import DomainError
from mixt.core.money import Money, format_money
from mixt.core.timezones import now_utc
from mixt.modules.crm import service as crm
from mixt.modules.pricing.models import (
    PackageBenefit,
    PriceBook,
    PriceBookEntry,
    PriceBookMarketAssignment,
    PriceBookVersion,
)
from mixt.modules.pricing.service import active_selection, tier_choices
from mixt.modules.reference import service as reference
from mixt.modules.settings import service as settings

CUSTOMER_MESSAGES = {
    "MARKET_NOT_CONFIRMED": "Our team will confirm the right package options for you shortly.",
    "MARKET_EXCLUDED": "Our team will get back to you about availability in your country.",
    "MARKET_NOT_ACTIVE": "Our team will get back to you about availability in your country.",
    "NO_APPROVED_PRICING_FOR_MARKET": "Our team will confirm the package options for your country shortly.",
    "PLAN_NOT_OFFERED_IN_MARKET": (
        "That plan isn't available in your country; our team can suggest the options that are."
    ),
    "TIER_DECISION_REQUIRED": "Our team will confirm the package options for you shortly.",
    "QUANTITY_NOT_OFFERED": "That isn't one of our standard packages; our team can suggest the closest options.",
}


class PricingUnavailable(DomainError):
    """No option can be offered. ``code`` is one of docs/04 §6 error codes; a person takes over."""

    status = 409
    title = "Pricing not available"

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(
            code,
            detail,
            customer_safe_message=CUSTOMER_MESSAGES[code],
            escalation_required=True,
            **extra,
        )


@dataclass(frozen=True)
class Option:
    option_ref: str
    price_book_id: uuid.UUID
    price_book_code: str
    version_id: uuid.UUID
    version_no: int
    entry_id: uuid.UUID
    package_code: str
    display_name: str
    quantity: Decimal
    unit_type: str
    minutes_per_unit: int
    package_total_minor: int
    currency: str
    package_total_display: str
    advertised_unit_rate_minor: int | None
    derived_unit_rate_minor: int
    derived_unit_rate_display: str
    plan_type: str
    tier_label: str | None
    benefits: tuple[str, ...]
    tier_selection_id: uuid.UUID | None


@dataclass(frozen=True)
class Resolution:
    market_id: uuid.UUID
    market_country: str
    at: datetime
    options: tuple[Option, ...]


def _live_versions(db: Session, market_id: uuid.UUID, at: datetime) -> list[tuple[PriceBook, PriceBookVersion]]:
    """Public books with a confirmed assignment to this market and a version active at ``at``."""
    rows = db.execute(
        select(PriceBook, PriceBookVersion)
        .join(PriceBookMarketAssignment, PriceBookMarketAssignment.price_book_id == PriceBook.id)
        .join(PriceBookVersion, PriceBookVersion.price_book_id == PriceBook.id)
        .where(
            PriceBookMarketAssignment.market_id == market_id,
            PriceBookMarketAssignment.assignment_status == "confirmed",
            PriceBook.audience == "public",
            PriceBook.archived_at.is_(None),
            PriceBook.plan_type != "promotional",  # promotions are separate offers (ADR-15), never list prices
            PriceBookVersion.status == "active",
            PriceBookVersion.effective_from <= at,
            or_(PriceBookVersion.effective_to.is_(None), PriceBookVersion.effective_to > at),
        )
        .order_by(PriceBook.code)
    )
    return [(b, v) for b, v in rows.tuples()]


def resolve_options(
    db: Session,
    account_id: uuid.UUID,
    *,
    plan_type: str | None = None,
    quantity: Decimal | None = None,
    opportunity_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> Resolution:
    """Callers check that the person or agent may see this account; this function never infers a market."""
    when = at or now_utc()
    account = crm.account_for_system(db, account_id)
    # 1. market: confirmed by a person, never inferred from currency, phone prefix or curriculum (ADR-13)
    if account.market_id is None or account.market_confirmed_at is None:
        raise PricingUnavailable("MARKET_NOT_CONFIRMED", "The customer's pricing market has not been confirmed.")
    market = reference.require_market(db, account.market_id)
    if market.status != "active":
        raise PricingUnavailable("MARKET_NOT_ACTIVE", f"{market.name} is not an active market.")

    # 3-4. candidates: live public books of this market (special assignments arrive in a later increment)
    live = _live_versions(db, market.id, when)
    if not live:
        raise PricingUnavailable(
            "NO_APPROVED_PRICING_FOR_MARKET", f"There is no active, approved pricing for {market.name}."
        )
    if plan_type is not None:
        live = [(b, v) for b, v in live if b.plan_type == plan_type]
        if not live:
            raise PricingUnavailable(
                "PLAN_NOT_OFFERED_IN_MARKET", f"No active {plan_type} pricing exists for {market.name}."
            )

    # 5. tiers: where the market has several VALID books of a plan type (active or not), a person must
    #    have chosen one for this customer. Never decided by price, label or customer data.
    choices = tier_choices(db, market.id)
    chosen: list[tuple[PriceBook, PriceBookVersion, uuid.UUID | None]] = []
    for plan in sorted({b.plan_type for b, _ in live}):
        in_plan = [(b, v) for b, v in live if b.plan_type == plan]
        if plan not in choices:
            chosen += [(b, v, None) for b, v in in_plan]
            continue
        mode = settings.get_value(db, "pricing.tier_selection_mode", "market", str(market.id))
        if mode == "market_default":
            defaults = set(
                db.scalars(
                    select(PriceBookMarketAssignment.price_book_id).where(
                        PriceBookMarketAssignment.market_id == market.id,
                        PriceBookMarketAssignment.is_market_default,
                        PriceBookMarketAssignment.assignment_status == "confirmed",
                    )
                )
            )
            chosen += [(b, v, None) for b, v in in_plan if b.id in defaults]
            continue
        selection = active_selection(db, account.id, market.id, plan, opportunity_id) if mode == "manual" else None
        if selection is None:
            raise PricingUnavailable(
                "TIER_DECISION_REQUIRED",
                f"{market.name} has several valid {plan} tiers or schedules; a person must choose one for this "
                "customer.",
                choices=[b.code for b in choices[plan]],
            )
        match = [(b, v, selection.id) for b, v in in_plan if b.id == selection.price_book_id]
        if not match:
            raise PricingUnavailable(
                "NO_APPROVED_PRICING_FOR_MARKET",
                "The tier chosen for this customer has no active, approved pricing yet.",
            )
        chosen += match
    if not chosen:
        raise PricingUnavailable("NO_APPROVED_PRICING_FOR_MARKET", f"No offerable pricing for {market.name}.")

    # 6. entries, exact quantity only (no interpolation, no rate x hours)
    options: list[Option] = []
    nearest: set[str] = set()
    for book, version, selection_id in chosen:
        currency = reference.currency(db, book.currency_code)
        entries = list(
            db.scalars(
                select(PriceBookEntry)
                .where(PriceBookEntry.price_book_version_id == version.id, PriceBookEntry.is_purchasable)
                .order_by(PriceBookEntry.quantity)
            )
        )
        if quantity is not None:
            exact = [e for e in entries if Decimal(e.quantity) == quantity]
            if not exact:
                below = [e for e in entries if Decimal(e.quantity) < quantity][-1:]
                above = [e for e in entries if Decimal(e.quantity) > quantity][:1]
                nearest.update(f"{book.code} {e.display_name}" for e in below + above)
            entries = exact
        benefits = tuple(
            db.scalars(
                select(PackageBenefit.customer_facing_text)
                .where(PackageBenefit.price_book_version_id == version.id, PackageBenefit.status == "approved")
                .order_by(PackageBenefit.sort_order)
            )
        )
        for e in entries:
            ref = hashlib.sha256(f"{version.content_hash}:{e.id}:{market.id}".encode()).hexdigest()[:24]
            options.append(
                Option(
                    option_ref=f"opt_{ref}",
                    price_book_id=book.id,
                    price_book_code=book.code,
                    version_id=version.id,
                    version_no=version.version_no,
                    entry_id=e.id,
                    package_code=e.package_code,
                    display_name=e.display_name,
                    quantity=Decimal(e.quantity),
                    unit_type=book.unit_type,
                    minutes_per_unit=version.session_minutes_per_unit,
                    package_total_minor=e.package_total_minor,
                    currency=book.currency_code,
                    package_total_display=format_money(
                        Money(e.package_total_minor, book.currency_code), currency.minor_units
                    ),
                    advertised_unit_rate_minor=e.advertised_unit_rate_minor,
                    derived_unit_rate_minor=e.derived_unit_rate_minor,
                    derived_unit_rate_display=format_money(
                        Money(e.derived_unit_rate_minor, book.currency_code), currency.minor_units
                    )
                    + f" per {book.unit_type} (derived)",
                    plan_type=book.plan_type,
                    tier_label=book.tier_label,
                    benefits=benefits,
                    tier_selection_id=selection_id,
                )
            )
    if quantity is not None and not options:
        raise PricingUnavailable(
            "QUANTITY_NOT_OFFERED",
            f"No active package has exactly {quantity.normalize()} units.",
            nearest_options=sorted(nearest),
        )
    # 7. minimum-purchase rules: none confirmed (Q-PRC-10). 8. promotions: none (promotions.enabled = false).
    return Resolution(market.id, market.country_code, when, tuple(options))
