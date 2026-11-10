"""Website enquiry form (docs/07 §6): bot protection, consent capture, lead intake.

- Off until ``web.enquiries.enabled`` is switched on (an approved privacy notice and consent
  wording are needed first: Q-CMP-01, Q-WEB-01).
- A hidden honeypot field is always checked; a filled honeypot gets the same answer as a real
  enquiry, so bots learn nothing. Cloudflare Turnstile is optional (``web.bot_protection``,
  Q-WEB-02); its secret is stored on a ``website_forms`` integration connection.
- Each consent tick box is recorded separately, only for a wording version listed in
  ``web.consent_wording_versions``. An unticked box records nothing (it never withdraws consent
  given elsewhere).
- The enquiry goes through normal lead intake (source ``website_form``): new households are
  unowned and wait in the pool; out-of-market countries are flagged for review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR
from mixt.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from mixt.core.logging import get_logger
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.modules.crm import service as crm
from mixt.modules.identity.access import system_access
from mixt.modules.integrations import service as integrations
from mixt.modules.leads import service as leads
from mixt.modules.settings import service as settings

log = get_logger("mixt.web_enquiries")
TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
CONSENT_PURPOSES = ("service_messages", "marketing_whatsapp", "marketing_email")
_INTAKE_PERMISSIONS = (
    "crm.accounts.create",
    "crm.accounts.update",
    "crm.accounts.read",
    "crm.accounts.read_all",
    "crm.students.manage",
    "crm.consents.record",
    "leads.create",
)

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport  # noqa: PLW0603
    _transport = transport


@dataclass
class Enquiry:
    guardian_first_name: str
    guardian_last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    student_first_name: str | None = None
    student_curriculum: str | None = None
    student_grade: str | None = None
    message: str | None = None
    consents: dict[str, bool] = field(default_factory=dict)
    consent_wording_version: str | None = None
    utm: dict[str, str] = field(default_factory=dict)
    landing_page: str | None = None
    referrer: str | None = None
    honeypot: str | None = None
    bot_token: str | None = None


def allowed_origins(db: Session) -> list[str]:
    return [str(o) for o in settings.get_value(db, "web.allowed_origins") or []]


def _turnstile_ok(db: Session, token: str | None, ip: str | None) -> bool:
    connection = next(iter(integrations.connections_for(db, "website_forms")), None)
    secret = integrations.secret(db, connection.id, "client_secret") if connection else None
    if secret is None:
        raise ServiceUnavailable("BOT_CHECK_UNAVAILABLE", "The form's bot check is not set up. Please try later.")
    if not token:
        return False
    data = {"secret": secret, "response": token, **({"remoteip": ip} if ip else {})}
    try:
        with httpx.Client(transport=_transport, timeout=5.0) as client:
            body = client.post(TURNSTILE_URL, data=data).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceUnavailable(
            "BOT_CHECK_UNAVAILABLE", "The form's bot check did not answer. Please try again."
        ) from exc
    return bool(isinstance(body, dict) and body.get("success") is True)


def _check_consents(db: Session, enquiry: Enquiry, phone: str | None, email: str | None) -> list[str]:
    ticked = [p for p in CONSENT_PURPOSES if enquiry.consents.get(p)]
    unknown = set(enquiry.consents) - set(CONSENT_PURPOSES)
    if unknown:
        raise ValidationFailed("UNKNOWN_CONSENT", f"Unknown consent purpose(s): {', '.join(sorted(unknown))}.")
    if not ticked:
        return []
    versions = settings.get_value(db, "web.consent_wording_versions") or []
    if enquiry.consent_wording_version not in versions:
        raise ValidationFailed(
            "UNKNOWN_CONSENT_WORDING", "The consent wording on this form is not an approved version."
        )
    if "marketing_email" in ticked and email is None:
        raise ValidationFailed("EMAIL_REQUIRED", "Give an email address to receive emails.")
    if ("marketing_whatsapp" in ticked or "service_messages" in ticked) and phone is None:
        raise ValidationFailed("PHONE_REQUIRED", "Give a phone number to receive WhatsApp messages.")
    return ticked


def submit(db: Session, enquiry: Enquiry, ip: str | None) -> None:
    """Accept an enquiry from the website. Raises on invalid input; returns quietly for bots."""
    if not settings.get_value(db, "web.enquiries.enabled"):
        raise NotFound("ENQUIRIES_OFF", "This form is not accepting enquiries yet.")
    if enquiry.honeypot:
        log.info("enquiry_honeypot")
        return
    if settings.get_value(db, "web.bot_protection") == "turnstile" and not _turnstile_ok(db, enquiry.bot_token, ip):
        raise ValidationFailed("BOT_CHECK_FAILED", "We could not confirm you are not a robot. Please try again.")
    phone = normalize_phone(enquiry.phone, enquiry.country) if enquiry.phone else None
    email = normalize_email(enquiry.email) if enquiry.email else None
    ticked = _check_consents(db, enquiry, phone, email)
    utm: dict[str, Any] = {k: v[:200] for k, v in enquiry.utm.items() if v}
    if enquiry.landing_page:
        utm["landing_page"] = enquiry.landing_page[:500]
    if enquiry.referrer:
        utm["referrer"] = enquiry.referrer[:500]
    access = system_access(*_INTAKE_PERMISSIONS)
    result = leads.intake(
        db,
        SYSTEM_ACTOR,
        access,
        leads.LeadInput(
            source_code="website_form",
            guardian_first_name=enquiry.guardian_first_name,
            guardian_last_name=enquiry.guardian_last_name,
            email=email,
            phone=phone,
            country=enquiry.country,
            student_first_name=enquiry.student_first_name,
            student_curriculum=enquiry.student_curriculum,
            student_grade=enquiry.student_grade,
            message=enquiry.message,
            utm=utm or None,
        ),
        owner_user_id=None,
        owner_explicit=False,
        manual=False,
    )
    lead = result.lead
    if not ticked or lead.account_id is None:
        return
    contact_id = lead.contact_id
    if contact_id is None:  # matched an existing household: the contact that has this number or address
        for kind, value in (("phone", phone), ("email", email)):
            if value and contact_id is None:
                contact_id = crm.contact_with_point(db, lead.account_id, kind, value)
    if contact_id is None:
        return
    evidence = {
        "form": "website_enquiry",
        "wording_version": enquiry.consent_wording_version,
        "lead_id": str(lead.id),
        "landing_page": (enquiry.landing_page or "")[:500] or None,
    }
    for purpose in ticked:
        crm.record_consent(db, SYSTEM_ACTOR, access, contact_id, purpose, "granted", "consent", "web_form", evidence)
