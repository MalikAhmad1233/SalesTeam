"""Further paths: role grants, owner bootstrap (CLI), contact and student updates, list filters."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt import cli
from mixt.core.context import SYSTEM_ACTOR
from mixt.core.errors import Conflict, ValidationFailed
from mixt.modules.identity import service as identity
from mixt.modules.identity.models import User
from tests.conftest import make_user, market_id

ACCOUNTS = "/api/v1/crm/accounts"


def _v(record: dict[str, Any]) -> dict[str, str]:
    return {"If-Match": f'"{record["version"]}"'}


# ------------------------------------------------------------------ roles


def test_grant_and_revoke_market_scoped_role(as_user: Any, db: Session) -> None:
    owner, me = as_user([("owner", None)])
    target = make_user(db, [("sales_rep", None)])
    ae = str(market_id(db, "AE"))
    granted = owner.post(
        f"/api/v1/users/{target.id}/roles", json={"roles": [{"role": "sales_manager", "market_id": ae}]}
    )
    assert granted.status_code == 200
    assert {"role": "sales_manager", "market_id": ae} in granted.json()["roles"]
    again = owner.post(f"/api/v1/users/{target.id}/roles", json={"roles": [{"role": "sales_manager", "market_id": ae}]})
    assert again.json()["roles"].count({"role": "sales_manager", "market_id": ae}) == 1  # idempotent
    revoked = owner.post(f"/api/v1/users/{target.id}/roles/revoke", json={"role": "sales_manager", "market_id": ae})
    assert {"role": "sales_manager", "market_id": ae} not in revoked.json()["roles"]
    missing = owner.post(f"/api/v1/users/{target.id}/roles/revoke", json={"role": "finance"})
    assert missing.status_code == 404
    unknown = owner.post(f"/api/v1/users/{target.id}/roles", json={"roles": [{"role": "wizard"}]})
    assert unknown.json()["code"] == "UNKNOWN_ROLE"
    own_owner = owner.post(f"/api/v1/users/{me.id}/roles/revoke", json={"role": "owner"})
    assert own_owner.json()["code"] == "CANNOT_REVOKE_OWN_OWNER_ROLE"
    users = {u["email"]: u for u in owner.get("/api/v1/users").json()}
    assert target.user.email in users


def test_user_creation_validation(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    base = {"email": "tz@mixt-test.example", "full_name": "Tz", "roles": [{"role": "sales_rep"}]}
    bad_tz = admin.post("/api/v1/users", json={**base, "temporary_password": "Temporary-pass-123", "timezone": "Mars"})
    assert bad_tz.json()["code"] == "INVALID_TIMEZONE"
    weak = admin.post("/api/v1/users", json={**base, "temporary_password": "aaaaaaaaaaaa"})
    assert weak.json()["code"] == "WEAK_PASSWORD"
    status = admin.patch("/api/v1/users/00000000-0000-7000-8000-000000000999/status", json={"status": "active"})
    assert status.status_code == 404
    invalid = admin.patch("/api/v1/users/00000000-0000-7000-8000-000000000999/status", json={"status": "gone"})
    assert invalid.json()["code"] == "INVALID_STATUS"


# ------------------------------------------------------------------ owner bootstrap


class _NoCloseSession:
    def __init__(self, db: Session) -> None:
        self._db = db

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    def close(self) -> None:  # the test fixture owns the real session
        pass


def test_bootstrap_owner_service_and_cli(db: Session, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        pytest.skip("database already has users")
    with pytest.raises(ValidationFailed):
        identity.bootstrap_owner(db, SYSTEM_ACTOR, "owner@mixt-test.example", "Owner", "short")
    monkeypatch.setattr(cli, "_sessionmaker_for", lambda _url: lambda: _NoCloseSession(db))
    monkeypatch.setenv("MIXT_OWNER_PASSWORD", "Strong-passphrase-2026")
    assert cli.main(["create-owner", "--email", "Owner@Mixt-Test.example", "--name", "First Owner"]) == 0
    assert "Owner created" in capsys.readouterr().out
    owner = db.scalar(select(User).where(User.email == "owner@mixt-test.example"))
    assert owner is not None and not owner.must_change_password
    assert identity.roles_of(db, owner.principal_id) == [("owner", None)]
    with pytest.raises(Conflict):
        identity.bootstrap_owner(db, SYSTEM_ACTOR, "second@mixt-test.example", "Second", "Strong-passphrase-2026")
    assert cli.main(["create-owner", "--email", "third@mixt-test.example", "--name", "Third"]) == 1


# ------------------------------------------------------------------ contacts and students


def test_contact_updates(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = rep.post(ACCOUNTS, json={"display_name": "Update household"}).json()
    first = rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "guardian", "first_name": "Mona"}).json()
    second = rep.post(f"{ACCOUNTS}/{account['id']}/contacts", json={"role": "payer", "first_name": "Omar"}).json()
    renamed = rep.patch(
        f"/api/v1/crm/contacts/{second['id']}",
        json={"last_name": "Haddad", "timezone": "Asia/Qatar", "preferred_language": "ar", "is_primary": True},
        headers=_v(second),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["is_primary"] and renamed.json()["last_name"] == "Haddad"
    contacts = {c["id"]: c for c in rep.get(f"{ACCOUNTS}/{account['id']}/contacts").json()}
    assert not contacts[first["id"]]["is_primary"]
    current = contacts[second["id"]]
    unset = rep.patch(f"/api/v1/crm/contacts/{second['id']}", json={"is_primary": False}, headers=_v(current))
    assert unset.json()["code"] == "PRIMARY_REQUIRED"
    bad_lang = rep.patch(f"/api/v1/crm/contacts/{second['id']}", json={"preferred_language": "xx"}, headers=_v(current))
    assert bad_lang.json()["code"] == "UNKNOWN_LANGUAGE"
    stale = rep.patch(f"/api/v1/crm/contacts/{second['id']}", json={"first_name": "O"}, headers=_v(second))
    assert stale.status_code == 412
    points = rep.get(f"/api/v1/crm/contacts/{first['id']}/contact-points").json()
    assert points == []


def test_student_updates(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    account = rep.post(ACCOUNTS, json={"display_name": "Student household"}).json()
    student = rep.post(f"{ACCOUNTS}/{account['id']}/students", json={"first_name": "Sara"}).json()
    updated = rep.patch(
        f"/api/v1/crm/students/{student['id']}",
        json={
            "curriculum_code": "SABIS",
            "status": "active",
            "timezone": "Asia/Kuwait",
            "country_of_study": "KW",
            "grade_text": "Grade 8",
            "goals": "Improve maths",
        },
        headers=_v(student),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["status"] == "active" and body["grade_text"] == "Grade 8" and body["country_of_study"] == "KW"
    assert rep.patch(f"/api/v1/crm/students/{student['id']}", json={"status": "x"}, headers=_v(body)).status_code == 422
    assert (
        rep.patch(f"/api/v1/crm/students/{student['id']}", json={"first_name": "S"}, headers=_v(student)).status_code
        == 412
    )
    students = rep.get(f"{ACCOUNTS}/{account['id']}/students").json()
    assert [s["id"] for s in students] == [student["id"]]
    no_curriculum = rep.post(f"{ACCOUNTS}/{account['id']}/students", json={"first_name": "Yusuf"}).json()
    needs_curriculum = rep.post(
        f"/api/v1/crm/students/{no_curriculum['id']}/subjects",
        json={"subject_name": "Physics", "exam_board_code": "OCR"},
    )
    assert needs_curriculum.json()["code"] == "CURRICULUM_REQUIRED"


def test_account_filters_and_fields(as_user: Any) -> None:
    rep, me = as_user([("sales_rep", None)])
    lead = rep.post(
        ACCOUNTS,
        json={"display_name": "Filter lead", "timezone": "Asia/Dubai", "preferred_language": "en", "is_vip": True},
    ).json()
    assert lead["timezone"] == "Asia/Dubai" and lead["is_vip"] is True
    rep.post(ACCOUNTS, json={"display_name": "Filter abroad", "country_of_residence": "US"})
    out_of_market = rep.get(f"{ACCOUNTS}?lifecycle_stage=out_of_market").json()
    assert {a["display_name"] for a in out_of_market} >= {"Filter abroad"}
    mine = rep.get(f"{ACCOUNTS}?owner_user_id={me.id}").json()
    assert all(a["owner_user_id"] == str(me.id) for a in mine)
    page = rep.get(f"{ACCOUNTS}?limit=1").json()
    older = rep.get(f"{ACCOUNTS}?limit=1&before_id={page[0]['id']}").json()
    assert older and older[0]["id"] < page[0]["id"]
    assert (
        rep.post(ACCOUNTS, json={"display_name": "Bad", "country_of_residence": "ZZ"}).json()["code"]
        == "UNKNOWN_COUNTRY"
    )
    assert rep.post(ACCOUNTS, json={"display_name": "Bad", "timezone": "Nowhere"}).json()["code"] == "INVALID_TIMEZONE"
    assert rep.post(ACCOUNTS, json={"display_name": "Bad", "kind": "company"}).json()["code"] == "INVALID_KIND"
    assert rep.post(ACCOUNTS, json={"display_name": "   "}).json()["code"] == "NAME_REQUIRED"


def test_inactive_market_cannot_be_confirmed(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    market = admin.post(
        "/api/v1/reference/markets",
        json={"country_code": "JO", "name": "Jordan", "default_timezone": "Asia/Amman", "decision_ref": "BD-099"},
    ).json()
    account = admin.post(ACCOUNTS, json={"display_name": "Planned market household"}).json()
    response = admin.post(
        f"{ACCOUNTS}/{account['id']}/market-confirmation",
        json={"market_id": market["id"], "note": "Family lives in Amman"},
        headers=_v(account),
    )
    assert response.json()["code"] == "MARKET_NOT_ACTIVE"
