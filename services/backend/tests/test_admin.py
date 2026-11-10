"""Users and roles, reference data, the settings register and the audit API."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.modules.audit.models import AuditLog
from mixt.modules.settings.registry import DEFINITIONS
from tests.conftest import make_user, market_id, sign_in

REPO_ROOT = Path(__file__).resolve().parents[3]

# ------------------------------------------------------------------ users and roles


def test_admin_creates_user_with_temporary_password(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    response = admin.post(
        "/api/v1/users",
        json={
            "email": "New.Rep@Mixt-Test.example",
            "full_name": "New Rep",
            "temporary_password": "Temporary-pass-123",
            "roles": [{"role": "sales_rep"}],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.rep@mixt-test.example"
    assert body["must_change_password"] is True
    assert body["roles"] == [{"role": "sales_rep", "market_id": None}]
    duplicate = admin.post(
        "/api/v1/users",
        json={
            "email": "new.rep@mixt-test.example",
            "full_name": "Again",
            "temporary_password": "Temporary-pass-123",
            "roles": [{"role": "sales_rep"}],
        },
    )
    assert duplicate.status_code == 409


def test_cannot_grant_roles_beyond_own_permissions(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    response = admin.post(
        "/api/v1/users",
        json={
            "email": "x@mixt-test.example",
            "full_name": "X",
            "temporary_password": "Temporary-pass-123",
            "roles": [{"role": "owner"}],
        },
    )
    assert response.status_code == 403 and response.json()["code"] == "CANNOT_GRANT_ROLE"


def test_rep_cannot_manage_users(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert rep.get("/api/v1/users").status_code == 403
    assert (
        rep.post(
            "/api/v1/users",
            json={
                "email": "a@b.example",
                "full_name": "A",
                "temporary_password": "x" * 12,
                "roles": [{"role": "sales_rep"}],
            },
        ).status_code
        == 403
    )


def test_deactivation_revokes_sessions(as_user: Any, app_factory: Any, db: Session) -> None:
    owner, _ = as_user([("owner", None)])
    other_client = app_factory()
    target = make_user(db, [("sales_rep", None)])
    sign_in(other_client, db, target)
    assert other_client.get("/api/v1/auth/me").status_code == 200
    assert owner.patch(f"/api/v1/users/{target.id}/status", json={"status": "deactivated"}).status_code == 200
    assert other_client.get("/api/v1/auth/me").status_code == 401


def test_cannot_deactivate_self(as_user: Any) -> None:
    owner, me = as_user([("owner", None)])
    assert owner.patch(f"/api/v1/users/{me.id}/status", json={"status": "suspended"}).status_code == 409


def test_roles_listing(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    roles = {r["key"]: r for r in admin.get("/api/v1/roles").json()}
    assert set(roles) == {
        "owner",
        "admin",
        "pricing_manager",
        "sales_manager",
        "sales_rep",
        "finance",
        "tutor_coordinator",
        "analyst",
    }
    assert "crm.students.learning_needs.read" not in roles["sales_rep"]["permissions"]


# ------------------------------------------------------------------ reference data


def test_reference_lists(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    markets = rep.get("/api/v1/reference/markets").json()
    assert len(markets) == 13 and "US" not in {m["country_code"] for m in markets}
    countries = {c["code"]: c for c in rep.get("/api/v1/reference/countries").json()}
    assert countries["US"]["is_excluded"] is True
    curricula = {c["code"]: c for c in rep.get("/api/v1/reference/curricula").json()}
    assert set(curricula) == {"IRISH", "SABIS", "AMERICAN", "BRITISH"}
    assert {b["code"] for b in curricula["BRITISH"]["exam_boards"]} == {"CAMBRIDGE", "PEARSON_EDEXCEL", "AQA", "OCR"}
    currencies = {c["code"]: c for c in rep.get("/api/v1/reference/currencies").json()}
    assert currencies["KWD"]["minor_units"] == 3 and currencies["USD"]["display_prefix"] == "USD "


def test_us_market_refused_by_api(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    response = admin.post(
        "/api/v1/reference/markets",
        json={
            "country_code": "US",
            "name": "United States",
            "default_timezone": "America/New_York",
            "decision_ref": "BD-099",
        },
    )
    assert response.status_code == 422 and response.json()["code"] == "MARKET_COUNTRY_EXCLUDED"


def test_new_market_needs_decision_reference(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    body = {"country_code": "JO", "name": "Jordan", "default_timezone": "Asia/Amman", "decision_ref": "maybe"}
    assert admin.post("/api/v1/reference/markets", json=body).json()["code"] == "DECISION_REF_REQUIRED"
    body["decision_ref"] = "BD-099"
    created = admin.post("/api/v1/reference/markets", json=body)
    assert created.status_code == 201 and created.json()["status"] == "planned"
    assert admin.post("/api/v1/reference/markets", json=body).status_code == 409


def test_curriculum_addition_needs_owner_and_decision(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    body = {"code": "IB", "name": "International Baccalaureate", "decision_ref": "BD-099"}
    assert admin.post("/api/v1/reference/curricula", json=body).status_code == 403  # admin lacks permission
    owner, _ = as_user([("owner", None)])
    assert owner.post("/api/v1/reference/curricula", json={**body, "decision_ref": ""}).status_code == 422
    assert owner.post("/api/v1/reference/curricula", json=body).status_code == 201


# ------------------------------------------------------------------ settings register


def test_registry_definitions_are_consistent() -> None:
    keys = [d.key for d in DEFINITIONS]
    assert len(keys) == len(set(keys))
    for d in DEFINITIONS:
        jsonschema.validate(d.default, d.schema)
        assert "global" in d.scopes, d.key
        if d.status == "confirmed":
            assert d.decision_ref and re.match(r"^BD-\d{3}$", d.decision_ref), d.key
        else:
            assert d.decision_ref is None, d.key


def test_registry_matches_settings_document() -> None:
    """Every setting in code is documented in docs/13, and documented settings exist in code
    unless they are explicitly scheduled for a later increment."""
    doc = (REPO_ROOT / "docs" / "13-configurable-settings.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`([a-z_]+(?:\.[a-z_<>]+)+)`", doc))
    documented = {k for k in documented if "." in k and not k.startswith(("pricing.tier.", "change_type"))}
    in_code = {d.key for d in DEFINITIONS}
    later: set[str] = set()  # settings documented but scheduled for a later increment
    assert in_code - documented == set(), "settings missing from docs/13"
    missing = {
        k
        for k in documented - in_code - later
        if k.split(".")[0]
        in {
            "pricing",
            "quotations",
            "promotions",
            "benefits",
            "markets",
            "crm",
            "channels",
            "messaging",
            "ai",
            "scheduling",
            "tutors",
            "payments",
            "ledger",
            "retention",
            "referrals",
            "auth",
            "infra",
            "privacy",
            "notifications",
        }
    }
    assert missing == set(), "settings documented but not implemented"


def test_confirmed_decisions_are_not_outstanding(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    all_settings = {s["key"]: s for s in rep.get("/api/v1/settings").json()}
    assert all_settings["pricing.catalogue_complete"] == {
        **all_settings["pricing.catalogue_complete"],
        "value": False,
        "status": "confirmed",
        "decision_ref": "BD-017",
    }
    assert all_settings["markets.operating"]["decision_ref"] == "BD-004"
    assert "US" not in all_settings["markets.operating"]["value"]
    assert all_settings["crm.curricula"]["value"] == ["IRISH", "SABIS", "AMERICAN", "BRITISH"]
    outstanding = {s["key"] for s in rep.get("/api/v1/settings/outstanding").json()}
    assert "pricing.tier_selection_mode" in outstanding and "infra.region" in outstanding
    assert "pricing.catalogue_complete" not in outstanding and "crm.curricula" not in outstanding


def test_setting_change_rules(as_user: Any, db: Session) -> None:
    manager, _ = as_user([("sales_manager", None)])
    url = "/api/v1/settings/crm.lead_assignment"
    assert manager.put(url, json={"value": "magic", "status": "safe_default"}).json()["code"] == "INVALID_SETTING_VALUE"
    assert manager.put(url, json={"value": "rules", "status": "confirmed"}).json()["code"] == "DECISION_REF_REQUIRED"
    changed = manager.put(url, json={"value": "rules", "status": "confirmed", "decision_ref": "BD-040"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["value"] == "rules" and changed.json()["status"] == "confirmed"
    stale = manager.put(url, json={"value": "manual", "status": "safe_default", "expected_version": 99})
    assert stale.status_code == 412
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "setting_changed").order_by(AuditLog.id.desc()))
    assert (
        entry is not None and entry.changes is not None and entry.changes["value"] == {"from": "manual", "to": "rules"}
    )


def test_setting_permissions_and_dual_approval(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    denied = rep.put("/api/v1/settings/crm.lead_assignment", json={"value": "rules", "status": "safe_default"})
    assert denied.status_code == 403
    owner, _ = as_user([("owner", None)])
    dual = owner.put(
        "/api/v1/settings/pricing.catalogue_complete",
        json={"value": True, "status": "confirmed", "decision_ref": "BD-050"},
    )
    assert dual.status_code == 409 and dual.json()["code"] == "DUAL_APPROVAL_REQUIRED"


def test_scoped_setting_falls_back_to_global(as_user: Any, db: Session) -> None:
    owner, _ = as_user([("owner", None)])
    ae = str(market_id(db, "AE"))
    set_scoped = owner.put(
        "/api/v1/settings/markets.mixt_ai_rollout",
        json={"value": "crm_only", "status": "safe_default", "scope_type": "market", "scope_id": ae},
    )
    assert set_scoped.status_code == 200 and set_scoped.json()["source"] == "scoped"
    detail = owner.get("/api/v1/settings/markets.mixt_ai_rollout").json()
    assert detail["value"] == "off" and detail["scoped_overrides"][0]["value"] == "crm_only"
    bad_scope = owner.put(
        "/api/v1/settings/pricing.market_basis",
        json={"value": "staff_confirmed", "status": "safe_default", "scope_type": "market", "scope_id": ae},
    )
    assert bad_scope.json()["code"] == "INVALID_SCOPE"


@pytest.mark.parametrize("key", ["does.not.exist"])
def test_unknown_setting(as_user: Any, key: str) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert rep.get(f"/api/v1/settings/{key}").status_code == 404


# ------------------------------------------------------------------ audit API


def test_audit_api(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    assert rep.get("/api/v1/audit").status_code == 403
    admin, _ = as_user([("admin", None)])
    created = admin.post("/api/v1/crm/accounts", json={"display_name": "Audited household"}).json()
    entries = admin.get(f"/api/v1/audit?entity_type=account&entity_id={created['id']}").json()
    assert entries[0]["action"] == "account_created"
    verification = admin.post("/api/v1/audit/verify").json()
    assert verification["ok"] is True and verification["rows_checked"] > 0
