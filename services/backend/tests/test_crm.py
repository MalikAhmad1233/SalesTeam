"""CRM business rules: markets, visibility, contacts, consents, students."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mixt.modules.audit.models import AuditLog
from mixt.modules.crm.models import Student
from tests.conftest import make_team, make_user, market_id, sign_in

ACCOUNTS = "/api/v1/crm/accounts"


def _create(api: Any, **body: Any) -> dict[str, Any]:
    response = api.post(ACCOUNTS, json={"display_name": "Household", **body})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _v(record: dict[str, Any]) -> dict[str, str]:
    return {"If-Match": f'"{record["version"]}"'}


# ------------------------------------------------------------------ markets (ADR-13, BD-005)


def test_market_is_never_inferred(as_user: Any) -> None:
    """+1 phone, American curriculum and a UAE residence must not set a pricing market."""
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep, display_name="Expat family", country_of_residence="AE")
    assert account["market_id"] is None and account["lifecycle_stage"] == "lead"
    contact = rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "guardian", "first_name": "Sam"}).json()
    point = rep.post(
        f"/api/v1/crm/contacts/{contact['id']}/contact-points", json={"kind": "whatsapp", "value": "+1 202 555 0143"}
    )
    assert point.status_code == 201 and point.json()["value"] == "+12025550143"
    student = rep.post(
        f"{ACCOUNTS}/{account['id']}/students", json={"first_name": "Alex", "curriculum_code": "AMERICAN"}
    )
    assert student.status_code == 201
    assert rep.get(f"{ACCOUNTS}/{account['id']}").json()["market_id"] is None


def test_us_residents_are_out_of_market(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep, country_of_residence="US")
    assert account["lifecycle_stage"] == "out_of_market" and account["market_id"] is None
    moved = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"country_of_residence": "QA"}, headers=_v(account)).json()
    assert moved["lifecycle_stage"] == "lead"
    back = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"country_of_residence": "US"}, headers=_v(moved)).json()
    assert back["lifecycle_stage"] == "out_of_market"


def test_market_confirmation_by_a_person(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep, country_of_residence="AE")
    url = f"{ACCOUNTS}/{account['id']}/market-confirmation"
    ae = str(market_id(db, "AE"))
    assert rep.post(url, json={"market_id": ae, "note": "Parent lives in Dubai"}).json()["code"] == "VERSION_REQUIRED"
    assert (
        rep.post(url, json={"market_id": ae, "note": "ok"}, headers=_v(account)).json()["code"]
        == "CONFIRMATION_NOTE_REQUIRED"
    )
    confirmed = rep.post(url, json={"market_id": ae, "note": "Parent lives in Dubai"}, headers=_v(account))
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["market_id"] == ae and body["market_confirmed_at"] is not None
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == "account_market_confirmed", AuditLog.entity_id == account["id"])
    )
    assert entry is not None and entry.changes is not None and entry.changes["note"] == "Parent lives in Dubai"


def test_no_market_exists_for_the_us(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert db.execute(text("SELECT count(*) FROM markets WHERE country_code = 'US'")).scalar_one() == 0
    account = _create(rep, country_of_residence="US")
    response = rep.post(
        f"{ACCOUNTS}/{account['id']}/market-confirmation",
        json={"market_id": "00000000-0000-7000-8000-00000000dead", "note": "trying a made-up market"},
        headers=_v(account),
    )
    assert response.status_code == 404


def test_lifecycle_customer_is_system_managed(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    response = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"lifecycle_stage": "customer"}, headers=_v(account))
    assert response.json()["code"] == "LIFECYCLE_MANAGED_BY_SYSTEM"


def test_optimistic_locking(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    first = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"display_name": "First edit"}, headers=_v(account))
    assert first.status_code == 200 and first.headers["ETag"] == '"2"'
    stale = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"display_name": "Stale edit"}, headers=_v(account))
    assert stale.status_code == 412 and stale.json()["code"] == "VERSION_MISMATCH"
    assert rep.patch(f"{ACCOUNTS}/{account['id']}", json={"display_name": "No version"}).status_code == 428


def test_unknown_fields_are_rejected(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    response = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"market_id": "x"}, headers=_v(account))
    assert response.status_code == 422  # market can only be set via confirmation


# ------------------------------------------------------------------ visibility


def test_reps_only_see_their_own_and_pool(as_user: Any, app_factory: Any, db: Session) -> None:
    rep_a, user_a = as_user([("sales_rep", None)])
    other = app_factory()
    user_b = make_user(db, [("sales_rep", None)])
    rep_b = sign_in(other, db, user_b)
    mine = _create(rep_a, display_name="A's household")
    assert mine["owner_user_id"] == str(user_a.id)
    assert rep_b.get(f"{ACCOUNTS}/{mine['id']}").status_code == 404  # not revealed
    assert mine["id"] not in {a["id"] for a in rep_b.get(ACCOUNTS).json()}

    manager, _ = as_user([("sales_manager", None)])
    pool = manager.post(ACCOUNTS, json={"display_name": "Unassigned household", "owner_user_id": None}).json()
    assert pool["owner_user_id"] is None
    assert rep_b.get(f"{ACCOUNTS}/{pool['id']}").status_code == 200  # pool visible by default
    assert manager.get(f"{ACCOUNTS}/{mine['id']}").status_code == 200  # unscoped manager sees all

    manager.put("/api/v1/settings/crm.unassigned_pool_visible_to_reps", json={"value": False, "status": "safe_default"})
    assert rep_b.get(f"{ACCOUNTS}/{pool['id']}").status_code == 404


def test_team_lead_sees_team_accounts(as_user: Any, app_factory: Any, db: Session) -> None:
    rep, rep_user = as_user([("sales_rep", None)])
    account = _create(rep)
    lead_user = make_user(db, [("sales_rep", None)])
    make_team(db, lead_user, [rep_user])
    lead = sign_in(app_factory(), db, lead_user)
    assert lead.get(f"{ACCOUNTS}/{account['id']}").status_code == 200


def test_market_scoped_manager(as_user: Any, app_factory: Any, db: Session) -> None:
    owner, _ = as_user([("owner", None)])
    uae = _create(owner, display_name="Dubai household", country_of_residence="AE", owner_user_id=None)
    uk = _create(owner, display_name="London household", country_of_residence="GB", owner_user_id=None)
    manager_user = make_user(db, [("sales_manager", market_id(db, "AE"))])
    manager = sign_in(app_factory(), db, manager_user)
    # The manager is market-scoped: read_all only for the UAE.
    visible = {a["id"] for a in manager.get(ACCOUNTS).json()}
    assert uae["id"] in visible
    # The UK account is only visible because it is in the unassigned pool, not through the UAE scope.
    owner.put("/api/v1/settings/crm.unassigned_pool_visible_to_reps", json={"value": False, "status": "safe_default"})
    visible = {a["id"] for a in manager.get(ACCOUNTS).json()}
    assert uae["id"] in visible and uk["id"] not in visible


def test_owner_assignment_needs_permission(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    response = rep.post(ACCOUNTS, json={"display_name": "X", "owner_user_id": None})
    assert response.status_code == 403
    account = _create(rep)
    patch = rep.patch(f"{ACCOUNTS}/{account['id']}", json={"owner_user_id": None}, headers=_v(account))
    assert patch.status_code == 403


def test_search(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep, display_name="Al-Mansouri family")
    found = rep.get(f"{ACCOUNTS}?search=mansouri").json()
    assert [a["id"] for a in found] == [account["id"]]
    assert rep.get(f"{ACCOUNTS}?search={account['account_number']}").json()[0]["id"] == account["id"]
    assert rep.get(f"{ACCOUNTS}?search=%25").json() == []  # wildcards are escaped


# ------------------------------------------------------------------ contacts and consents


def test_contacts_and_primary_flag(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    first = rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "guardian", "first_name": "Mona"}).json()
    assert first["is_primary"] is True
    second = rep.post(
        f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "payer", "first_name": "Omar", "is_primary": True}
    ).json()
    contacts = {c["id"]: c for c in rep.get(f"{ACCOUNTS}/{account['id']}/contacts").json()}
    assert contacts[second["id"]]["is_primary"] and not contacts[first["id"]]["is_primary"]
    assert rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "boss", "first_name": "X"}).status_code == 422
    assert rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "guardian"}).status_code == 422


def test_contact_points_and_duplicates(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    a = _create(rep, country_of_residence="AE")
    b = _create(rep, country_of_residence="AE")
    ca = rep.post(f"{ACCOUNTS}/{a['id']}/contacts", json={"role": "guardian", "first_name": "A"}).json()
    cb = rep.post(f"{ACCOUNTS}/{b['id']}/contacts", json={"role": "guardian", "first_name": "B"}).json()
    first = rep.post(f"/api/v1/crm/contacts/{ca['id']}/contact-points", json={"kind": "phone", "value": "050 123 4567"})
    assert first.json()["value"] == "+971501234567" and first.json()["possible_duplicate"] is False
    dup = rep.post(f"/api/v1/crm/contacts/{cb['id']}/contact-points", json={"kind": "phone", "value": "+971501234567"})
    assert dup.json()["possible_duplicate"] is True
    email = rep.post(
        f"/api/v1/crm/contacts/{ca['id']}/contact-points", json={"kind": "email", "value": "Mona@Example.COM"}
    )
    assert email.json()["value"] == "mona@example.com"
    bad = rep.post(f"/api/v1/crm/contacts/{ca['id']}/contact-points", json={"kind": "phone", "value": "123"})
    assert bad.json()["code"] == "INVALID_PHONE_NUMBER"


def test_consent_history_is_append_only(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    contact = rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "guardian", "first_name": "Mona"}).json()
    url = f"/api/v1/crm/contacts/{contact['id']}/consents"
    base = {"purpose": "marketing_whatsapp", "legal_basis": "consent", "source": "staff_logged"}
    assert rep.post(url, json={**base, "status": "granted", "evidence": {}}).json()["code"] == "EVIDENCE_REQUIRED"
    assert rep.post(url, json={**base, "status": "granted", "evidence": {"said": "yes on call"}}).status_code == 201
    assert rep.post(url, json={**base, "status": "withdrawn", "evidence": {"said": "STOP"}}).status_code == 201
    assert rep.post(url, json={**base, "status": "maybe", "evidence": {"x": 1}}).json()["code"] == "INVALID_CONSENT"
    consents = rep.get(url).json()
    assert len(consents["history"]) == 2
    assert [c["status"] for c in consents["current"]] == ["withdrawn"]


# ------------------------------------------------------------------ students


def test_student_academic_profile(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    student = rep.post(
        f"{ACCOUNTS}/{account['id']}/students",
        json={"first_name": "Layla", "birth_year": 2010, "curriculum_code": "BRITISH", "grade_text": "Year 10"},
    ).json()
    subject = rep.post(
        f"/api/v1/crm/students/{student['id']}/subjects",
        json={
            "subject_name": "Mathematics",
            "exam_board_code": "PEARSON_EDEXCEL",
            "qualification_code": "IGCSE",
            "target_grade": "8",
        },
    )
    assert subject.status_code == 201, subject.text
    exam = rep.post(
        f"/api/v1/crm/students/{student['id']}/exams",
        json={"student_subject_id": subject.json()["id"], "exam_session": "May/June 2027"},
    )
    assert exam.status_code == 201
    full = rep.get(f"/api/v1/crm/students/{student['id']}").json()
    assert full["subjects"][0]["exam_board_id"] == subject.json()["exam_board_id"]
    assert full["exams"][0]["exam_session"] == "May/June 2027"
    assert rep.post(f"/api/v1/crm/students/{student['id']}/exams", json={}).json()["code"] == "EXAM_WHEN_REQUIRED"


def test_student_validation_rules(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    url = f"{ACCOUNTS}/{account['id']}/students"
    assert rep.post(url, json={"first_name": "A", "curriculum_code": "IB"}).json()["code"] == "UNKNOWN_CURRICULUM"
    assert rep.post(url, json={"first_name": "A", "date_of_birth": "2010-01-01"}).status_code == 422
    assert rep.post(url, json={"first_name": "A", "birth_year": 1800}).json()["code"] == "INVALID_BIRTH_YEAR"
    irish = rep.post(url, json={"first_name": "Niamh", "curriculum_code": "IRISH"}).json()
    wrong_board = rep.post(
        f"/api/v1/crm/students/{irish['id']}/subjects", json={"subject_name": "Maths", "exam_board_code": "AQA"}
    )
    assert wrong_board.json()["code"] == "BOARD_NOT_IN_CURRICULUM"


def test_learning_needs_are_restricted_and_encrypted(as_user: Any, app_factory: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = _create(rep)
    url = f"{ACCOUNTS}/{account['id']}/students"
    denied = rep.post(url, json={"first_name": "Omar", "learning_needs": "Dyslexia support"})
    assert denied.status_code == 403
    student = rep.post(url, json={"first_name": "Omar"}).json()

    manager_user = make_user(db, [("sales_manager", None)])
    manager = sign_in(app_factory(), db, manager_user)
    updated = manager.patch(
        f"/api/v1/crm/students/{student['id']}", json={"learning_needs": "Dyslexia support"}, headers=_v(student)
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["learning_needs"] == "Dyslexia support"

    seen_by_rep = rep.get(f"/api/v1/crm/students/{student['id']}").json()
    assert seen_by_rep["learning_needs"] is None and seen_by_rep["learning_needs_restricted"] is True

    stored = db.get(Student, student["id"])
    assert stored is not None and stored.learning_needs_ciphertext is not None
    assert b"Dyslexia" not in stored.learning_needs_ciphertext
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "student_updated", AuditLog.entity_id == student["id"]))
    assert entry is not None and "Dyslexia" not in str(entry.changes)
