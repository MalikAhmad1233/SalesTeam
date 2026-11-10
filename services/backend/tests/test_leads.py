"""Lead intake, out-of-market handling, spreadsheet import, duplicates and merges."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.modules.crm.models import Account, Consent, Contact, Student
from mixt.modules.engagement.models import Task
from mixt.modules.events import service as events
from mixt.modules.leads.models import LeadImportBatch
from mixt.modules.pipeline.models import Opportunity
from tests.conftest import make_user, market_id, sign_in

LEADS = "/api/v1/leads"


def _lead(api: Any, **body: Any) -> Any:
    payload = {
        "guardian_first_name": "Mona",
        "guardian_last_name": "Haddad",
        "phone": "+971 50 123 4567",
        "country": "AE",
        **body,
    }
    return api.post(LEADS, json=payload)


def test_new_enquiry_creates_household_contact_student_and_opportunity(as_user: Any, db: Session) -> None:
    rep, me = as_user([("sales_rep", None)])
    response = _lead(
        rep,
        email="Mona@Example.com",
        student_first_name="Layla",
        student_curriculum="british",
        student_grade="Year 10",
        message="Needs IGCSE maths help",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "new_account" and body["created_household"] is True
    assert body["opportunity_id"] is not None and body["account_id"] is not None
    account = db.get(Account, body["account_id"])
    assert account is not None and account.owner_user_id == me.id
    assert account.market_id is None  # never inferred from country, phone or curriculum (ADR-13)
    assert account.first_touch_lead_source_id is not None
    contact = db.scalar(select(Contact).where(Contact.account_id == account.id))
    assert contact is not None and contact.is_primary and contact.last_name == "Haddad"
    student = db.scalar(select(Student).where(Student.account_id == account.id))
    assert student is not None and student.grade_text == "Year 10"
    opportunity = db.get(Opportunity, body["opportunity_id"])
    assert opportunity is not None and opportunity.stage_key == "new" and str(opportunity.source_lead_id) == body["id"]
    assert db.scalar(select(Consent.id).where(Consent.contact_id == contact.id)) is None  # no consent invented


def test_repeat_enquiry_matches_existing_household(as_user: Any, app_factory: Any, db: Session) -> None:
    rep, rep_user = as_user([("sales_rep", None)])
    first = _lead(rep).json()
    other_user = make_user(db, [("sales_rep", None)])
    other = sign_in(app_factory(), db, other_user)
    second = _lead(other, guardian_first_name="M.", phone="050 123 4567")  # same number, local format
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["status"] == "matched" and body["created_household"] is False
    assert body["account_id"] is None and body["linked_to_hidden_household"] is True  # not revealed to rep B
    assert db.scalar(select(Account).where(Account.id == first["account_id"])) is not None
    task = db.scalar(select(Task).where(Task.account_id == first["account_id"], Task.source == "system"))
    assert task is not None and task.assignee_user_id == rep_user.id
    opportunities = db.scalars(select(Opportunity).where(Opportunity.account_id == first["account_id"])).all()
    assert len(opportunities) == 1  # the open opportunity is reused


def test_us_enquiry_is_out_of_market(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    body = _lead(rep, phone="+1 202 555 0143", country="US").json()
    assert body["status"] == "out_of_market" and body["opportunity_id"] is None
    account = db.get(Account, body["account_id"])
    assert account is not None and account.lifecycle_stage == "out_of_market" and account.market_id is None
    assert db.scalar(select(Opportunity.id).where(Opportunity.account_id == account.id)) is None
    manager, _ = as_user([("sales_manager", None)])
    queue = manager.get(f"{LEADS}?status=out_of_market").json()
    assert body["id"] in {lead["id"] for lead in queue}
    reviewed = manager.post(
        f"{LEADS}/{body['id']}/review", json={"decision": "rejected", "note": "Outside our markets"}
    )
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "rejected"
    assert rep.post(f"{LEADS}/{body['id']}/review", json={"decision": "spam", "note": "x"}).status_code == 403


def test_intake_validation(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert _lead(rep, phone=None).json()["code"] == "CONTACT_REQUIRED"
    assert _lead(rep, guardian_first_name=None, guardian_last_name=None).json()["code"] == "NAME_REQUIRED"
    assert _lead(rep, source="import").json()["code"] == "SOURCE_NOT_MANUAL"
    assert _lead(rep, source="nowhere").json()["code"] == "UNKNOWN_LEAD_SOURCE"
    assert _lead(rep, country="ZZ").json()["code"] == "UNKNOWN_COUNTRY"
    assert _lead(rep, student_first_name="A", student_curriculum="IB").json()["code"] == "UNKNOWN_CURRICULUM"
    assert _lead(rep, phone="12").json()["code"] == "INVALID_PHONE_NUMBER"
    sources = {s["code"] for s in rep.get(f"{LEADS}/sources").json()}
    assert {"manual", "meta_lead_ads", "import", "referral"} <= sources


def test_owner_rules_on_intake(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert _lead(rep, owner_user_id=None).status_code == 403  # reps cannot put leads in the pool
    manager, _ = as_user([("sales_manager", None)])
    pooled = _lead(manager, phone="+971 50 765 4321", owner_user_id=None).json()
    account = db.get(Account, pooled["account_id"])
    assert account is not None and account.owner_user_id is None


def test_campaigns_and_attribution(as_user: Any) -> None:
    manager, _ = as_user([("sales_manager", None)])
    campaign = manager.post(f"{LEADS}/campaigns", json={"source": "meta_lead_ads", "name": "Autumn IGCSE"})
    assert campaign.status_code == 201
    dup = manager.post(f"{LEADS}/campaigns", json={"source": "meta_lead_ads", "name": "Autumn IGCSE"})
    assert dup.status_code == 409
    wrong = _lead(manager, source="referral", campaign_id=campaign.json()["id"])
    assert wrong.json()["code"] == "INVALID_CAMPAIGN"
    ok = _lead(manager, source="meta_lead_ads", campaign_id=campaign.json()["id"], utm={"utm_source": "facebook"})
    assert ok.status_code == 201
    listed = manager.get(f"{LEADS}?campaign_id={campaign.json()['id']}").json()
    assert [lead["id"] for lead in listed] == [ok.json()["id"]]


def test_similar_names_raise_duplicate_candidates(as_user: Any) -> None:
    manager, _ = as_user([("sales_manager", None)])
    first = _lead(manager, household_name="Al Mansouri family", phone="+971 50 111 2222").json()
    second = _lead(manager, household_name="Al-Mansouri family", phone="+971 50 333 4444").json()
    assert second["duplicate_candidates"] == 1
    candidates = manager.get("/api/v1/crm/duplicates").json()
    pair = next(c for c in candidates if c["account_id"] == second["account_id"])
    assert pair["candidate_account_id"] == first["account_id"]


# ------------------------------------------------------------------ spreadsheet import

CSV = (
    "household_name,guardian_first_name,email,phone,country,student_first_name,student_curriculum,student_grade\n"
    "Khan family,Sara,sara@example.com,+44 7911 123456,GB,Ali,BRITISH,Year 11\n"
    ",Omar,,,AE,,,\n"
    "Lee family,Min,min@example.com,,KR,Joon,IB,Grade 9\n"
    "Khan again,Sara,sara@example.com,,GB,,,\n"
    "Tan family,Wei,wei@example.com,+65 9123 4567,SG,,,\n"
)


def _upload(api: Any, content: str, **form: str) -> Any:
    return api.client.post(
        f"{LEADS}/imports",
        files={"file": ("leads.csv", content.encode(), "text/csv")},
        data=form,
        headers={"X-CSRF-Token": api.csrf},
    )


def test_import_validate_then_commit(as_user: Any, db: Session) -> None:
    manager, me = as_user([("sales_manager", None)])
    validated = _upload(manager, CSV, default_owner_user_id=str(me.id))
    assert validated.status_code == 201, validated.text
    report = validated.json()
    assert (report["row_count"], report["valid_count"], report["error_count"]) == (5, 2, 3)
    errors = {r["row"]: r["errors"] for r in report["rows"] if not r["ok"]}
    assert "email or phone is required" in errors[2]
    assert any("confirmed curricula" in e for e in errors[3])
    assert any("same email/phone as row 1" in e for e in errors[4])
    assert "Q-CMP-10" in report["note"]
    assert db.scalar(select(Account.id).where(Account.display_name == "Khan family")) is None  # nothing yet

    committed = manager.post(f"{LEADS}/imports/{report['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported_count"] == 2
    outcomes = {r["row"]: r["outcome"] for r in committed.json()["rows"]}
    assert outcomes[1] == "new_account" and outcomes[2] == "skipped (invalid)"
    assert all("data" not in r for r in committed.json()["rows"])  # personal data removed after import
    khan = db.scalar(select(Account).where(Account.display_name == "Khan family"))
    assert khan is not None and khan.owner_user_id == me.id
    batch = db.get(LeadImportBatch, report["id"])
    assert batch is not None and "sara@example.com" not in str(batch.report)
    assert manager.post(f"{LEADS}/imports/{report['id']}/commit").status_code == 409


def test_import_file_checks_and_permissions(as_user: Any) -> None:
    manager, _ = as_user([("sales_manager", None)])
    assert _upload(manager, "name,shoe_size\nA,9\n").json()["code"] == "UNKNOWN_COLUMNS"
    assert _upload(manager, "household_name\n").json()["code"] == "FILE_EMPTY"
    bad = manager.client.post(
        f"{LEADS}/imports",
        files={"file": ("x.csv", b"\xff\xfe\x00bad", "text/csv")},
        headers={"X-CSRF-Token": manager.csrf},
    )
    assert bad.json()["code"] == "FILE_NOT_UTF8"
    discarded = _upload(manager, CSV).json()
    after = manager.post(f"{LEADS}/imports/{discarded['id']}/discard").json()
    assert after["status"] == "discarded" and all("data" not in r for r in after["rows"])
    rep, _ = as_user([("sales_rep", None)])
    assert _upload(rep, CSV).status_code == 403


# ------------------------------------------------------------------ merges


def test_merge_moves_everything(as_user: Any, db: Session) -> None:
    manager, _ = as_user([("sales_manager", None)])
    keep = _lead(manager, household_name="Rahman household", phone="+971 50 222 1111", student_first_name="Adam").json()
    dup = _lead(manager, household_name="Rahman household", phone="+971 50 222 9999", student_first_name="Zara").json()
    assert dup["duplicate_candidates"] == 1
    note = manager.post(f"/api/v1/crm/accounts/{dup['account_id']}/notes", json={"body": "Prefers evenings"})
    assert note.status_code == 201
    merged = manager.post(
        "/api/v1/crm/merges", json={"survivor_account_id": keep["account_id"], "merged_account_id": dup["account_id"]}
    )
    assert merged.status_code == 201, merged.text
    students = {s["first_name"] for s in manager.get(f"/api/v1/crm/accounts/{keep['account_id']}/students").json()}
    assert students == {"Adam", "Zara"}
    contacts = manager.get(f"/api/v1/crm/accounts/{keep['account_id']}/contacts").json()
    assert len(contacts) == 2 and sum(c["is_primary"] for c in contacts) == 1
    opportunities = db.scalars(select(Opportunity).where(Opportunity.account_id == keep["account_id"])).all()
    assert len(opportunities) == 2
    notes = manager.get(f"/api/v1/crm/accounts/{keep['account_id']}/notes").json()
    assert [n["body"] for n in notes] == ["Prefers evenings"]
    assert manager.get(f"/api/v1/crm/accounts/{dup['account_id']}").status_code == 200
    archived = db.get(Account, dup["account_id"])
    assert archived is not None and archived.status == "archived" and str(archived.merged_into_id) == keep["account_id"]
    assert manager.get("/api/v1/crm/duplicates").json() == []
    events.dispatch_outbox(db)
    titles = [a["title"] for a in manager.get(f"/api/v1/crm/accounts/{keep['account_id']}/timeline").json()]
    assert any(t.startswith("Merged with household") for t in titles)


def test_merge_rules(as_user: Any, db: Session) -> None:
    manager, _ = as_user([("sales_manager", None)])
    a = _lead(manager, household_name="Gulf A", phone="+971 50 444 1111").json()
    b = _lead(manager, household_name="Gulf B", phone="+974 3312 3456", country="QA").json()
    for lead, cc in ((a, "AE"), (b, "QA")):
        account = manager.get(f"/api/v1/crm/accounts/{lead['account_id']}").json()
        manager.post(
            f"/api/v1/crm/accounts/{lead['account_id']}/market-confirmation",
            json={"market_id": str(market_id(db, cc)), "note": "Confirmed on call"},
            headers={"If-Match": f'"{account["version"]}"'},
        )
    conflict = manager.post(
        "/api/v1/crm/merges", json={"survivor_account_id": a["account_id"], "merged_account_id": b["account_id"]}
    )
    assert conflict.json()["code"] == "MERGE_MARKET_CONFLICT"
    same = manager.post(
        "/api/v1/crm/merges", json={"survivor_account_id": a["account_id"], "merged_account_id": a["account_id"]}
    )
    assert same.json()["code"] == "MERGE_SAME_ACCOUNT"
    rep, _ = as_user([("sales_rep", None)])
    assert (
        rep.post(
            "/api/v1/crm/merges", json={"survivor_account_id": a["account_id"], "merged_account_id": b["account_id"]}
        ).status_code
        == 403
    )


def test_dismiss_duplicate(as_user: Any) -> None:
    manager, _ = as_user([("sales_manager", None)])
    _lead(manager, household_name="Fernandes family", phone="+971 50 555 1111")
    _lead(manager, household_name="Fernandes family", phone="+971 50 555 2222")
    candidate = manager.get("/api/v1/crm/duplicates").json()[0]
    dismissed = manager.post(f"/api/v1/crm/duplicates/{candidate['id']}/dismiss")
    assert dismissed.json()["status"] == "dismissed"
    assert manager.post(f"/api/v1/crm/duplicates/{candidate['id']}/dismiss").status_code == 409
