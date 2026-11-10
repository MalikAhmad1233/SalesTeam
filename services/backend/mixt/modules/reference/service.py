"""Reference data: markets, countries, currencies, languages, curricula."""

from __future__ import annotations

import re
import uuid

from psycopg.errors import CheckViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.timezones import InvalidTimezone, validate_timezone
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.reference.models import (
    Country,
    Currency,
    Curriculum,
    ExamBoard,
    Language,
    Market,
    Qualification,
)

_DECISION_REF = re.compile(r"^BD-[0-9]{3}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


def list_markets(db: Session) -> list[Market]:
    return list(db.scalars(select(Market).order_by(Market.name)))


def get_market(db: Session, market_id: uuid.UUID) -> Market | None:
    return db.get(Market, market_id)


def active_market_for_country(db: Session, country_code: str) -> Market | None:
    return db.scalar(select(Market).where(Market.country_code == country_code, Market.status == "active"))


def market_country_codes(db: Session, market_ids: frozenset[uuid.UUID]) -> list[str]:
    if not market_ids:
        return []
    return list(db.scalars(select(Market.country_code).where(Market.id.in_(market_ids))))


def list_countries(db: Session) -> list[Country]:
    return list(db.scalars(select(Country).order_by(Country.name)))


def country_exists(db: Session, code: str) -> bool:
    return db.get(Country, code) is not None


def list_currencies(db: Session) -> list[Currency]:
    return list(db.scalars(select(Currency).order_by(Currency.code)))


def currency(db: Session, code: str) -> Currency:
    found = db.get(Currency, code)
    if found is None:
        raise NotFound("CURRENCY_NOT_FOUND", f"Unknown currency {code}.")
    return found


def list_languages(db: Session) -> list[Language]:
    return list(db.scalars(select(Language).order_by(Language.name)))


def language_exists(db: Session, code: str) -> bool:
    return db.get(Language, code) is not None


def list_curricula(db: Session) -> list[tuple[Curriculum, list[ExamBoard], list[Qualification]]]:
    result = []
    for curriculum in db.scalars(select(Curriculum).order_by(Curriculum.name)):
        boards = list(
            db.scalars(select(ExamBoard).where(ExamBoard.curriculum_id == curriculum.id).order_by(ExamBoard.name))
        )
        quals = list(
            db.scalars(
                select(Qualification).where(Qualification.curriculum_id == curriculum.id).order_by(Qualification.name)
            )
        )
        result.append((curriculum, boards, quals))
    return result


def curriculum_by_code(db: Session, code: str) -> Curriculum | None:
    return db.scalar(select(Curriculum).where(Curriculum.code == code.upper(), Curriculum.is_active))


def get_curriculum(db: Session, curriculum_id: uuid.UUID) -> Curriculum | None:
    return db.get(Curriculum, curriculum_id)


def board_by_code(db: Session, curriculum_id: uuid.UUID, code: str) -> ExamBoard | None:
    return db.scalar(
        select(ExamBoard).where(
            ExamBoard.curriculum_id == curriculum_id, ExamBoard.code == code.upper(), ExamBoard.is_active
        )
    )


def qualification_by_code(db: Session, curriculum_id: uuid.UUID, code: str) -> Qualification | None:
    return db.scalar(
        select(Qualification).where(
            Qualification.curriculum_id == curriculum_id, Qualification.code == code.upper(), Qualification.is_active
        )
    )


def create_market(
    db: Session,
    actor: Actor,
    access: Access,
    country_code: str,
    name: str,
    default_timezone: str,
    decision_ref: str,
    status: str = "planned",
) -> Market:
    access.require("reference.markets.manage")
    code = country_code.upper()
    if not _DECISION_REF.match(decision_ref):
        raise ValidationFailed("DECISION_REF_REQUIRED", "A new market needs a decision-log reference such as 'BD-032'.")
    country = db.get(Country, code)
    if country is None:
        raise ValidationFailed("UNKNOWN_COUNTRY", f"'{code}' is not an ISO 3166-1 country code.")
    if country.is_excluded:
        raise ValidationFailed(
            "MARKET_COUNTRY_EXCLUDED",
            f"{country.name} is excluded and can never be a market ({country.exclusion_reason}).",
        )
    if status not in ("planned", "active", "inactive"):
        raise ValidationFailed("INVALID_STATUS", "Status must be planned, active or inactive.")
    try:
        validate_timezone(default_timezone)
    except InvalidTimezone as exc:
        raise ValidationFailed("INVALID_TIMEZONE", str(exc)) from exc
    if db.scalar(select(Market.id).where(Market.country_code == code)) is not None:
        raise Conflict("MARKET_EXISTS", f"A market for {code} already exists.")
    market = Market(
        country_code=code,
        name=name.strip(),
        status=status,
        default_timezone=default_timezone,
        decision_ref=decision_ref,
    )
    try:
        with db.begin_nested():
            db.add(market)
            db.flush()
    except IntegrityError as exc:  # database trigger DB-01 is the final safeguard
        if isinstance(exc.orig, CheckViolation):
            raise ValidationFailed("MARKET_COUNTRY_EXCLUDED", "This country can never be a market.") from exc
        raise
    audit.record(
        db,
        actor,
        "market_created",
        "market",
        market.id,
        {"country_code": code, "status": status, "decision_ref": decision_ref},
    )
    return market


def add_curriculum(db: Session, actor: Actor, access: Access, code: str, name: str, decision_ref: str) -> Curriculum:
    """Add a curriculum. BD-008: only with explicit approval, recorded as a decision-log reference."""
    access.require("reference.curricula.manage")
    if not _DECISION_REF.match(decision_ref):
        raise ValidationFailed(
            "DECISION_REF_REQUIRED",
            "Adding a curriculum needs Mixt's approval recorded in the decision log (e.g. 'BD-032').",
        )
    normalized = code.strip().upper()
    if not _CODE.match(normalized):
        raise ValidationFailed("INVALID_CODE", "Code must be upper-case letters, digits or underscores.")
    if db.scalar(select(Curriculum.id).where(Curriculum.code == normalized)) is not None:
        raise Conflict("CURRICULUM_EXISTS", f"Curriculum {normalized} already exists.")
    curriculum = Curriculum(code=normalized, name=name.strip(), decision_ref=decision_ref)
    db.add(curriculum)
    db.flush()
    audit.record(
        db, actor, "curriculum_added", "curriculum", curriculum.id, {"code": normalized, "decision_ref": decision_ref}
    )
    return curriculum


def require_market(db: Session, market_id: uuid.UUID) -> Market:
    market = db.get(Market, market_id)
    if market is None:
        raise NotFound("MARKET_NOT_FOUND", "Market not found.")
    return market
