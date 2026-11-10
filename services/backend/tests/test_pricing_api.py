"""Pricing over HTTP: the whole life of a price book, as two pricing managers and a sales manager would
use it through the dashboard."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from tests.conftest import make_user, market_id, sign_in

P = "/api/v1/pricing"
ACCOUNTS = "/api/v1/crm/accounts"


def _book(api: Any, code: str) -> dict[str, Any]:
    return next(b for b in api.get(f"{P}/books").json() if b["code"] == code)  # type: ignore[no-any-return]


def test_lifecycle_over_http(as_user: Any, app_factory: Any, db: Session) -> None:
    first, _ = as_user([("pricing_manager", None)])
    second_client = app_factory()
    second = sign_in(second_client, db, make_user(db, [("pricing_manager", None)]))
    third_client = app_factory()
    third = sign_in(third_client, db, make_user(db, [("owner", None)]))

    qatar = _book(first, "QA-QAR")
    detail = first.get(f"{P}/books/{qatar['id']}").json()
    assert [v["version_no"] for v in detail["versions"]] == [1]
    vid = detail["versions"][0]["id"]
    v = f"{P}/versions/{vid}"

    assert first.post(f"{v}/activate").json()["code"] == "INVALID_TRANSITION"
    bad = first.post(f"{v}/confirm-figures", json={"decision_ref": "maybe", "note": "Mixt said yes"})
    assert bad.status_code == 422 and bad.json()["code"] == "DECISION_REF_REQUIRED"
    assert (
        first.post(f"{v}/confirm-figures", json={"decision_ref": "BD-901", "note": "Mixt said yes"}).status_code == 200
    )
    taxed = first.post(f"{v}/tax", json={"treatment": "inclusive", "decision_ref": "BD-902"}).json()
    assert taxed["tax_treatment"] == "inclusive" and taxed["tax_treatment_ref"] == "BD-902"
    assert first.post(f"{v}/submit").json()["status"] == "in_review"
    assert first.post(f"{v}/approve").json()["code"] == "FOUR_EYES"
    assert second.post(f"{v}/approve").json()["approvals"] == 1
    approved = third.post(f"{v}/approve").json()
    assert approved["status"] == "approved" and approved["gate_passes"] is True and approved["content_hash"]
    back = first.post(f"{v}/return", json={"reason": "one more check"}).json()
    assert back["status"] == "draft" and back["approvals"] == 0
    first.post(f"{v}/submit")
    second.post(f"{v}/approve")
    third.post(f"{v}/approve")
    live = first.post(f"{v}/activate")
    assert live.status_code == 200 and live.json()["status"] == "active"
    assert _book(first, "QA-QAR")["active_version_no"] == 1

    seller = sign_in(app_factory(), db, make_user(db, [("sales_manager", None)]))  # its own browser
    household = seller.post(ACCOUNTS, json={"display_name": "Doha family"}).json()
    seller.post(
        f"{ACCOUNTS}/{household['id']}/market-confirmation",
        json={"market_id": str(market_id(db, "QA")), "note": "Parent lives in Doha"},
        headers={"If-Match": f'"{household["version"]}"'},
    )
    options = seller.get(f"/api/v1/accounts/{household['id']}/pricing/options", params={"quantity": "40"}).json()
    assert [(o["display_name"], o["package_total_display"]) for o in options["options"]] == [("40h", "QAR 2,280")]
    assert options["market_country"] == "QA" and options["options"][0]["option_ref"].startswith("opt_")
    missing = seller.get(f"/api/v1/accounts/{household['id']}/pricing/options", params={"quantity": "45"}).json()
    assert missing["code"] == "QUANTITY_NOT_OFFERED" and missing["nearest_options"] == ["QA-QAR 40h", "QA-QAR 60h"]

    retired = first.post(f"{v}/retire", json={"reason": "test complete"}).json()
    assert retired["status"] == "retired" and retired["effective_to"] is not None
    refused = seller.get(f"/api/v1/accounts/{household['id']}/pricing/options").json()
    assert refused["code"] == "NO_APPROVED_PRICING_FOR_MARKET"


def test_assignments_relationships_benefits_and_tiers(as_user: Any, db: Session) -> None:
    owner, _ = as_user([("owner", None)])
    usd = _book(owner, "USD-SCHEDULE-B")
    assert usd["assignments"] == []
    assigned = owner.post(
        f"{P}/books/{usd['id']}/assignments",
        json={"market_id": str(market_id(db, "SG")), "decision_ref": "BD-907", "note": "Q-MKT-01 answer (test)"},
    )
    assert assigned.status_code == 201 and assigned.json()["country_code"] == "SG"
    again = owner.post(
        f"{P}/books/{usd['id']}/assignments", json={"market_id": str(market_id(db, "SG")), "decision_ref": "BD-907"}
    )
    assert again.json()["code"] == "ALREADY_ASSIGNED"
    revoked = owner.post(f"{P}/assignments/{assigned.json()['id']}/revoke", json={"reason": "decided otherwise"})
    assert revoked.json()["status"] == "revoked"

    ireland = _book(owner, "IE-EUR-SCHEDULE-A")
    assignment = ireland["assignments"][0]
    assert assignment["requires_relationship_confirmation"] and assignment["relationship_confirmed_ref"] is None
    confirmed = owner.post(f"{P}/assignments/{assignment['id']}/confirm-relationship", json={"decision_ref": "BD-908"})
    assert confirmed.json()["relationship_confirmed_ref"] == "BD-908"
    uk = _book(owner, "UK-GBP-TIER-A")["assignments"][0]
    not_needed = owner.post(f"{P}/assignments/{uk['id']}/confirm-relationship", json={"decision_ref": "BD-908"})
    assert not_needed.json()["code"] == "NOT_REQUIRED"

    hk = _book(owner, "HK-HKD-PREMIUM")
    version = owner.get(f"{P}/versions/{hk['latest_version']['id']}").json()
    benefit = version["benefits"][0]
    assert benefit["status"] == "draft"
    assert owner.post(f"{P}/benefits/{benefit['id']}/approve").status_code == 204
    assert owner.post(f"{P}/benefits/{benefit['id']}/approve").json()["code"] == "ALREADY_APPROVED"
    after = owner.get(f"{P}/versions/{hk['latest_version']['id']}").json()
    assert after["benefits"][0]["status"] == "approved"
    assert next(g for g in after["gate"] if g["code"] == "G-06")["detail"].startswith("6 not approved")

    household = owner.post(ACCOUNTS, json={"display_name": "Dubai family"}).json()
    owner.post(
        f"{ACCOUNTS}/{household['id']}/market-confirmation",
        json={"market_id": str(market_id(db, "AE")), "note": "Parent lives in Dubai"},
        headers={"If-Match": f'"{household["version"]}"'},
    )
    tiers = owner.get(f"/api/v1/accounts/{household['id']}/pricing/tiers").json()
    choice = tiers["choices"][0]
    assert choice["plan_type"] == "standard" and choice["current"] is None
    assert all(b["has_active_pricing"] is False for b in choice["books"])
    picked = owner.post(
        f"/api/v1/accounts/{household['id']}/pricing/tiers",
        json={"price_book_id": choice["books"][1]["price_book_id"], "reason": "Agreed on the call"},
    ).json()
    withdrawn = owner.post(f"{P}/tier-selections/{picked['id']}/revoke", json={"reason": "parent changed mind"})
    assert withdrawn.json()["status"] == "revoked"
    assert owner.post(f"{P}/tier-selections/{picked['id']}/revoke", json={"reason": "again"}).json()["code"] == (
        "NOT_ACTIVE"
    )
