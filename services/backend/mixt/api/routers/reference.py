"""Reference data: markets, countries, currencies, languages, curricula."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, require
from mixt.core.db import get_session
from mixt.modules.reference import service as reference

router = APIRouter(prefix="/reference", tags=["reference"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MarketOut(_Out):
    id: uuid.UUID
    country_code: str
    name: str
    status: str
    default_timezone: str
    decision_ref: str | None


class CountryOut(_Out):
    code: str
    name: str
    is_excluded: bool
    exclusion_reason: str | None


class CurrencyOut(_Out):
    code: str
    name: str
    minor_units: int
    display_prefix: str


class LanguageOut(_Out):
    code: str
    name: str


class CodeNameOut(_Out):
    code: str
    name: str


class CurriculumOut(BaseModel):
    code: str
    name: str
    decision_ref: str
    exam_boards: list[CodeNameOut]
    qualifications: list[CodeNameOut]


class MarketIn(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=100)
    default_timezone: str
    decision_ref: str
    status: str = "planned"


class CurriculumIn(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=100)
    decision_ref: str


@router.get("/markets", response_model=list[MarketOut])
def markets(_: AuthContext = Depends(require("reference.read")), db: Session = Depends(get_session)) -> list[MarketOut]:
    return [MarketOut.model_validate(m) for m in reference.list_markets(db)]


@router.post("/markets", response_model=MarketOut, status_code=201)
def create_market(
    body: MarketIn, auth: AuthContext = Depends(require("reference.markets.manage")), db: Session = Depends(get_session)
) -> MarketOut:
    market = reference.create_market(
        db, auth.actor, auth.access, body.country_code, body.name, body.default_timezone, body.decision_ref, body.status
    )
    return MarketOut.model_validate(market)


@router.get("/countries", response_model=list[CountryOut])
def countries(
    _: AuthContext = Depends(require("reference.read")), db: Session = Depends(get_session)
) -> list[CountryOut]:
    return [CountryOut.model_validate(c) for c in reference.list_countries(db)]


@router.get("/currencies", response_model=list[CurrencyOut])
def currencies(
    _: AuthContext = Depends(require("reference.read")), db: Session = Depends(get_session)
) -> list[CurrencyOut]:
    return [CurrencyOut.model_validate(c) for c in reference.list_currencies(db)]


@router.get("/languages", response_model=list[LanguageOut])
def languages(
    _: AuthContext = Depends(require("reference.read")), db: Session = Depends(get_session)
) -> list[LanguageOut]:
    return [LanguageOut.model_validate(lang) for lang in reference.list_languages(db)]


@router.get("/curricula", response_model=list[CurriculumOut])
def curricula(
    _: AuthContext = Depends(require("reference.read")), db: Session = Depends(get_session)
) -> list[CurriculumOut]:
    return [
        CurriculumOut(
            code=c.code,
            name=c.name,
            decision_ref=c.decision_ref,
            exam_boards=[CodeNameOut.model_validate(b) for b in boards],
            qualifications=[CodeNameOut.model_validate(q) for q in quals],
        )
        for c, boards, quals in reference.list_curricula(db)
    ]


@router.post("/curricula", response_model=CurriculumOut, status_code=201)
def add_curriculum(
    body: CurriculumIn,
    auth: AuthContext = Depends(require("reference.curricula.manage")),
    db: Session = Depends(get_session),
) -> CurriculumOut:
    c = reference.add_curriculum(db, auth.actor, auth.access, body.code, body.name, body.decision_ref)
    return CurriculumOut(code=c.code, name=c.name, decision_ref=c.decision_ref, exam_boards=[], qualifications=[])
