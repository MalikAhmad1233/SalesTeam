"""Public endpoints called by Mixt's website (no sign-in). Served under ``/public/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api import throttle
from mixt.api.deps import client_ip
from mixt.core.db import get_session
from mixt.modules.leads import web_enquiries

router = APIRouter(prefix="/public/v1", tags=["public"])


class ConsentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_messages: bool = False
    marketing_whatsapp: bool = False
    marketing_email: bool = False


class UtmIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str | None = Field(default=None, max_length=200)
    medium: str | None = Field(default=None, max_length=200)
    campaign: str | None = Field(default=None, max_length=200)
    term: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=200)


class EnquiryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guardian_first_name: str = Field(min_length=1, max_length=100)
    guardian_last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    student_first_name: str | None = Field(default=None, max_length=100)
    student_curriculum: str | None = Field(default=None, max_length=40)
    student_grade: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)
    consents: ConsentsIn = Field(default_factory=ConsentsIn)
    consent_wording_version: str | None = Field(default=None, max_length=40)
    utm: UtmIn = Field(default_factory=UtmIn)
    landing_page: str | None = Field(default=None, max_length=500)
    referrer: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=200, description="Honeypot: must stay empty")
    bot_token: str | None = Field(default=None, max_length=4096)


class EnquiryOut(BaseModel):
    status: str


def _cors(request: Request, response: Response, db: Session) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # server-to-server or same-origin
    if origin not in web_enquiries.allowed_origins(db):
        return False
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    response.headers["Vary"] = "Origin"
    return True


@router.options("/enquiries", include_in_schema=False)
def enquiry_preflight(request: Request, db: Session = Depends(get_session)) -> Response:
    response = Response(status_code=204)
    if not _cors(request, response, db):
        return Response(status_code=403)
    return response


@router.post("/enquiries", response_model=EnquiryOut, status_code=202)
def submit_enquiry(
    body: EnquiryIn, request: Request, response: Response, db: Session = Depends(get_session)
) -> EnquiryOut:
    if not _cors(request, response, db):
        response.status_code = 403
        return EnquiryOut(status="origin_not_allowed")
    ip = client_ip(request)
    throttle.enforce("enquiry_per_ip", ip)
    web_enquiries.submit(
        db,
        web_enquiries.Enquiry(
            guardian_first_name=body.guardian_first_name,
            guardian_last_name=body.guardian_last_name,
            email=body.email,
            phone=body.phone,
            country=body.country,
            student_first_name=body.student_first_name,
            student_curriculum=body.student_curriculum,
            student_grade=body.student_grade,
            message=body.message,
            consents=body.consents.model_dump(),
            consent_wording_version=body.consent_wording_version,
            utm={k: v for k, v in body.utm.model_dump().items() if v},
            landing_page=body.landing_page,
            referrer=body.referrer,
            honeypot=body.website,
            bot_token=body.bot_token,
        ),
        ip,
    )
    return EnquiryOut(status="received")
