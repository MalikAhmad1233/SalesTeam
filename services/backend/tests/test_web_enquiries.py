"""Phase 3a: the website enquiry form (off by default, honeypot, Turnstile, consent wording, CORS)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR
from mixt.modules.crm import service as crm
from mixt.modules.crm.models import Account, Consent
from mixt.modules.identity.access import load_access, system_access
from mixt.modules.integrations import service as integrations
from mixt.modules.leads import web_enquiries
from mixt.modules.leads.models import Lead
from mixt.modules.settings import service as settings
from tests.conftest import TestUser, make_user

URL = "/public/v1/enquiries"
ORIGIN = "https://www.mixt.example"


@pytest.fixture
def owner(db: Session) -> TestUser:
    return make_user(db, [("owner", None)])


def _set(db: Session, owner: TestUser, key: str, value: Any) -> None:
    settings.change(db, owner.actor, load_access(db, owner.actor), key, value, "safe_default", None)


@pytest.fixture
def enabled(db: Session, owner: TestUser) -> TestUser:
    _set(db, owner, "web.enquiries.enabled", True)
    return owner


def _form(**extra: Any) -> dict[str, Any]:
    return {
        "guardian_first_name": "Aisha",
        "guardian_last_name": "Khan",
        "email": "aisha.khan@example.com",
        "phone": "+97455123451",
        "country": "QA",
        "student_first_name": "Omar",
        "message": "Looking for IGCSE maths support",
        "utm": {"source": "google", "medium": "cpc", "campaign": "autumn"},
        "landing_page": "https://www.mixt.example/igcse",
        **extra,
    }


def _leads(db: Session) -> list[Lead]:
    return list(db.scalars(select(Lead).where(Lead.submitted_email == "aisha.khan@example.com")))


def test_form_is_off_until_switched_on(db: Session, client: TestClient, owner: TestUser) -> None:
    response = client.post(URL, json=_form())
    assert response.status_code == 404 and response.json()["code"] == "ENQUIRIES_OFF"
    assert _leads(db) == []


def test_enquiry_becomes_an_unowned_lead_with_attribution(db: Session, client: TestClient, enabled: TestUser) -> None:
    response = client.post(URL, json=_form())
    assert response.status_code == 202 and response.json() == {"status": "received"}
    [lead] = _leads(db)
    assert lead.status == "new_account" and lead.submitted_phone == "+97455123451"
    assert lead.utm == {
        "source": "google",
        "medium": "cpc",
        "campaign": "autumn",
        "landing_page": "https://www.mixt.example/igcse",
    }
    account = db.get(Account, lead.account_id)
    assert account is not None and account.owner_user_id is None  # waits in the pool for a person
    assert db.scalar(select(Consent).where(Consent.contact_id == lead.contact_id)) is None  # nothing ticked
    assert client.post(URL, json=_form(phone="12")).json()["code"] == "INVALID_PHONE_NUMBER"
    assert client.post(URL, json=_form(extra_field="x")).status_code == 422


def test_honeypot_gets_the_same_answer_and_stores_nothing(db: Session, client: TestClient, enabled: TestUser) -> None:
    response = client.post(URL, json=_form(website="http://spam.example"))
    assert response.status_code == 202 and response.json() == {"status": "received"}
    assert _leads(db) == []


def test_consent_needs_an_approved_wording_version(db: Session, client: TestClient, enabled: TestUser) -> None:
    ticked = {"marketing_whatsapp": True, "marketing_email": True, "service_messages": True}
    refused = client.post(URL, json=_form(consents=ticked, consent_wording_version="2026-11-v1"))
    assert refused.status_code == 422 and refused.json()["code"] == "UNKNOWN_CONSENT_WORDING"
    _set(db, enabled, "web.consent_wording_versions", ["2026-11-v1"])
    no_phone = client.post(
        URL, json=_form(phone=None, consents={"marketing_whatsapp": True}, consent_wording_version="2026-11-v1")
    )
    assert no_phone.json()["code"] == "PHONE_REQUIRED"
    accepted = client.post(URL, json=_form(consents=ticked, consent_wording_version="2026-11-v1"))
    assert accepted.status_code == 202
    [lead] = _leads(db)
    assert lead.contact_id is not None
    consents = list(db.scalars(select(Consent).where(Consent.contact_id == lead.contact_id)))
    assert {c.purpose for c in consents} == set(ticked)
    assert all(c.status == "granted" and c.source == "web_form" for c in consents)
    assert consents[0].evidence["wording_version"] == "2026-11-v1"


def test_consent_from_an_existing_household_lands_on_its_contact(
    db: Session, client: TestClient, enabled: TestUser
) -> None:
    rep = make_user(db, [("sales_rep", None)])
    access = load_access(db, rep.actor)
    account = crm.create_account(db, rep.actor, access, "Khan family", country_of_residence="QA")
    contact = crm.add_contact(db, rep.actor, access, account.id, {"role": "guardian", "first_name": "Aisha"})
    crm.add_contact_point(db, rep.actor, access, contact.id, "email", "aisha.khan@example.com")
    _set(db, enabled, "web.consent_wording_versions", ["v1"])
    response = client.post(URL, json=_form(consents={"marketing_email": True}, consent_wording_version="v1"))
    assert response.status_code == 202
    [lead] = _leads(db)
    assert lead.status == "matched" and lead.account_id == account.id
    assert crm.latest_consent_status(db, contact.id, "marketing_email") == "granted"


def test_enquiries_are_rate_limited_per_address(app: Any, enabled: TestUser) -> None:
    with TestClient(app, base_url="https://testserver", client=("203.0.113.20", 4000)) as c:
        codes = [c.post(URL, json=_form(website="bot")).status_code for _ in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429
    with TestClient(app, base_url="https://testserver", client=("203.0.113.21", 4000)) as other:
        assert other.post(URL, json=_form(website="bot")).status_code == 202


@pytest.fixture
def turnstile() -> Iterator[list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        calls.append(form)
        return httpx.Response(200, json={"success": form.get("response") == "good-token"})

    web_enquiries.set_transport(httpx.MockTransport(handler))
    yield calls
    web_enquiries.set_transport(None)


def test_turnstile_bot_check(
    db: Session, client: TestClient, enabled: TestUser, turnstile: list[dict[str, Any]]
) -> None:
    admin = make_user(db, [("admin", None)])
    _set(db, enabled, "web.bot_protection", "turnstile")
    missing = client.post(URL, json=_form(bot_token="good-token"))
    assert missing.status_code == 503 and missing.json()["code"] == "BOT_CHECK_UNAVAILABLE"
    integrations.create_connection(
        db,
        admin.actor,
        load_access(db, admin.actor),
        "website_forms",
        "Website form",
        {"site": ORIGIN},
        {"client_secret": "turnstile-secret-0123"},
    )
    assert client.post(URL, json=_form(bot_token="bad-token")).json()["code"] == "BOT_CHECK_FAILED"
    assert client.post(URL, json=_form()).json()["code"] == "BOT_CHECK_FAILED"
    assert client.post(URL, json=_form(bot_token="good-token")).status_code == 202
    assert turnstile[-1]["secret"] == "turnstile-secret-0123" and len(_leads(db)) == 1


def test_browsers_only_from_listed_origins(db: Session, client: TestClient, enabled: TestUser) -> None:
    preflight = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
    assert client.options(URL, headers=preflight).status_code == 403
    assert client.post(URL, json=_form(website="x"), headers={"Origin": ORIGIN}).status_code == 403
    _set(db, enabled, "web.allowed_origins", [ORIGIN])
    allowed = client.options(URL, headers=preflight)
    assert allowed.status_code == 204 and allowed.headers["access-control-allow-origin"] == ORIGIN
    posted = client.post(URL, json=_form(), headers={"Origin": ORIGIN})
    assert posted.status_code == 202 and posted.headers["access-control-allow-origin"] == ORIGIN
    assert client.post(URL, json=_form(website="x"), headers={"Origin": "https://evil.example"}).status_code == 403


def test_system_access_is_limited_to_what_it_was_given() -> None:
    access = system_access("leads.create")
    assert access.has("leads.create") and not access.has("crm.accounts.create")
    assert access.user_id is None and access.principal_id == SYSTEM_ACTOR.principal_id
