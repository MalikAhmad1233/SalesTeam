"""Phase 2c quotations: built from resolved options, approvals by people, discount authority, checks V-01
to V-09, frozen snapshots, PDF from the snapshot, issue, outcome, price changes, revisions, expiry."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.crm import service as crm
from mixt.modules.identity.access import load_access
from mixt.modules.pipeline import service as pipeline
from mixt.modules.pricing import promotions, resolution
from mixt.modules.pricing import service as pricing
from mixt.modules.pricing.models import PriceBookEntry
from mixt.modules.quotations import pdf
from mixt.modules.quotations import service as quotations
from mixt.modules.settings import service as settings_service
from tests.conftest import TestUser, make_user, market_id, sign_in
from tests.test_pricing import _live, _version_id
from tests.test_pricing_2b import _enable


@pytest.fixture
def managers(db: Session) -> tuple[TestUser, TestUser]:
    return make_user(db, [("pricing_manager", None)]), make_user(db, [("pricing_manager", None)])


@pytest.fixture
def people(db: Session) -> dict[str, TestUser]:
    return {
        "rep": make_user(db, [("sales_rep", None)]),
        "manager": make_user(db, [("sales_manager", None)]),
        "manager2": make_user(db, [("sales_manager", None)]),
        "pricing": make_user(db, [("pricing_manager", None)]),
        "owner": make_user(db, [("owner", None)]),
    }


def _a(db: Session, user: TestUser) -> Any:
    return load_access(db, user.actor)


def _household(db: Session, rep: TestUser, country: str = "QA") -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(account, opportunity, contact) owned by the rep, market confirmed by a person."""
    access = _a(db, rep)
    account = crm.create_account(db, rep.actor, access, "Quote family")
    crm.confirm_market(
        db, rep.actor, access, account.id, market_id(db, country), "Parent confirmed it", account.version
    )
    opp = pipeline.create_opportunity_system(db, rep.actor, account.id, "Quote family: tutoring", rep.id)
    contact = crm.add_contact(db, rep.actor, access, account.id, {"role": "guardian", "first_name": "Aisha"})
    return account.id, opp.id, contact.id


def _entry(db: Session, code: str, quantity: int, no: int = 1) -> uuid.UUID:
    found = db.scalar(
        select(PriceBookEntry.id).where(
            PriceBookEntry.price_book_version_id == _version_id(db, code, no), PriceBookEntry.quantity == quantity
        )
    )
    assert found is not None
    return found


def _draft(db: Session, rep: TestUser, **line: Any) -> tuple[quotations.QuoteView, uuid.UUID]:
    account, opp, contact = _household(db, rep)
    view = quotations.create(db, rep.actor, _a(db, rep), account, opp, "Thank you for your interest")
    view = quotations.add_line(db, rep.actor, _a(db, rep), view.quote.id, _entry(db, "QA-QAR", 30), **line)
    return view, contact


def _approve(db: Session, user: TestUser, quote_id: uuid.UUID, capacity: str = "sales", **kw: Any) -> Any:
    return quotations.approve(db, user.actor, _a(db, user), quote_id, capacity, **kw)


def test_lines_come_only_from_offered_options(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    rep = people["rep"]
    account, opp, _contact = _household(db, rep)
    view = quotations.create(db, rep.actor, _a(db, rep), account, opp)
    with pytest.raises(resolution.PricingUnavailable) as nothing:  # nothing is active yet
        quotations.add_line(db, rep.actor, _a(db, rep), view.quote.id, _entry(db, "QA-QAR", 30))
    assert nothing.value.code == "NO_APPROVED_PRICING_FOR_MARKET"
    _live(db, "QA-QAR", *managers)
    view = quotations.add_line(db, rep.actor, _a(db, rep), view.quote.id, _entry(db, "QA-QAR", 30))
    line = view.lines[0]
    assert (line.price_book_code, line.price_book_version_no, line.display_name) == ("QA-QAR", 1, "30h")
    assert (line.list_total_minor, line.final_total_minor, line.currency_code) == (180000, 180000, "QAR")
    assert view.quote.total_minor == 180000 and view.quote.quote_number.startswith("Q-")
    with pytest.raises(ValidationFailed) as other_market:  # a UK entry is never an option for a Qatar customer
        quotations.add_line(db, rep.actor, _a(db, rep), view.quote.id, _entry(db, "UK-GBP-TIER-A", 30))
    assert other_market.value.code == "NOT_AN_OFFERED_OPTION"
    with pytest.raises(ValidationFailed) as wrong_opp:
        other_account, _o, _c = _household(db, rep)
        quotations.create(db, rep.actor, _a(db, rep), other_account, opp)
    assert wrong_opp.value.code == "OPPORTUNITY_NOT_IN_ACCOUNT"
    stranger = make_user(db, [("sales_rep", None)])
    with pytest.raises(NotFound):
        quotations.get(db, _a(db, stranger), view.quote.id)


def test_list_price_quote_needs_a_second_person_then_freezes(
    db: Session, managers: Any, people: dict[str, TestUser]
) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager = people["rep"], people["manager"]
    view, contact = _draft(db, rep)
    quote_id = view.quote.id
    submitted = quotations.submit(db, rep.actor, _a(db, rep), quote_id)
    assert submitted.quote.status == "pending_approval"
    assert submitted.needs == {"sales": True, "pricing": False, "reasons": ["list_price"]}
    with pytest.raises(PermissionDenied):
        quotations.approve(db, rep.actor, _a(db, rep), quote_id, "sales")  # reps cannot approve
    with pytest.raises(Conflict) as no_date:
        _approve(db, manager, quote_id)
    assert any(m.startswith("V-09") for m in no_date.value.extra["missing"])
    approved = _approve(db, manager, quote_id, valid_until=now_utc().date() + timedelta(days=14))
    assert approved.quote.status == "approved" and approved.quote.snapshot_hash
    snapshot = approved.quote.pricing_snapshot
    assert snapshot["lines"][0]["list_total"] == "QAR 1,800" and snapshot["totals"]["total"] == "QAR 1,800"
    assert snapshot["tax_treatment"] == "inclusive" and snapshot["market"]["country"] == "QA"
    with pytest.raises(Conflict):  # frozen: lines can no longer change
        quotations.remove_line(db, rep.actor, _a(db, rep), quote_id, approved.lines[0].id)
    issued = quotations.issue(db, rep.actor, _a(db, rep), quote_id, contact)
    assert issued.quote.status == "issued" and issued.quote.issued_via == "manual"
    first = pdf.render(issued.quote.pricing_snapshot, issued.quote.snapshot_hash, "Aisha")
    again = pdf.render(issued.quote.pricing_snapshot, issued.quote.snapshot_hash, "Aisha")
    assert first.startswith(b"%PDF") and first == again  # the same snapshot always gives the same document
    accepted = quotations.record_outcome(db, rep.actor, _a(db, rep), quote_id, "accepted", "Confirmed by WhatsApp")
    assert accepted.quote.status == "accepted"


def test_preparer_may_issue_list_price_when_mixt_says_so(
    db: Session, managers: Any, people: dict[str, TestUser]
) -> None:
    _live(db, "QA-QAR", *managers)
    owner = people["owner"]
    settings_service.change(
        db, owner.actor, _a(db, owner), "quotations.approval", "preparer_may_issue_list_price", "confirmed", "BD-940"
    )
    rep = people["rep"]
    view, _contact = _draft(db, rep)
    quotations.update_draft(
        db,
        rep.actor,
        _a(db, rep),
        view.quote.id,
        valid_until=now_utc().date() + timedelta(days=7),
        customer_note=None,
        internal_note=None,
        discount_reason=None,
    )
    assert quotations.submit(db, rep.actor, _a(db, rep), view.quote.id).quote.status == "approved"


def test_discounts_need_sales_and_pricing_approval(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager, pricing_user = people["rep"], people["manager"], people["pricing"]
    view, _contact = _draft(db, rep, discount_minor=10000)
    quote_id = view.quote.id
    assert view.quote.total_minor == 170000 and view.quote.discount_total_minor == 10000
    with pytest.raises(Conflict) as no_reason:
        quotations.submit(db, rep.actor, _a(db, rep), quote_id)
    assert any(m.startswith("V-06") for m in no_reason.value.extra["missing"])
    quotations.update_draft(
        db,
        rep.actor,
        _a(db, rep),
        quote_id,
        valid_until=now_utc().date() + timedelta(days=10),
        customer_note=None,
        internal_note=None,
        discount_reason="Second child joining",
    )
    pending = quotations.submit(db, rep.actor, _a(db, rep), quote_id)
    assert pending.needs["sales"] and pending.needs["pricing"]
    assert quote_id in {q.id for q in quotations.approval_inbox(db, _a(db, pricing_user))}  # sees it without CRM access
    assert quotations.get(db, _a(db, pricing_user), quote_id).quote.discount_total_minor == 10000
    after_sales = _approve(db, manager, quote_id)
    assert after_sales.quote.status == "pending_approval"  # nobody approves a discount alone (authority is empty)
    with pytest.raises(Conflict) as twice:
        _approve(db, manager, quote_id)
    assert twice.value.code == "APPROVAL_NOT_NEEDED"
    final = _approve(db, pricing_user, quote_id, capacity="pricing")
    assert final.quote.status == "approved"
    assert {a["capacity"] for a in final.quote.pricing_snapshot["approvals"]} == {"sales", "pricing"}


def test_discount_authority_lets_one_person_approve_within_limits(
    db: Session, managers: Any, people: dict[str, TestUser]
) -> None:
    _live(db, "QA-QAR", *managers)
    owner, rep, manager = people["owner"], people["rep"], people["manager"]
    with pytest.raises(ValidationFailed):
        settings_service.change(
            db,
            owner.actor,
            _a(db, owner),
            "pricing.discount_authority",
            {"wizard": {"max_percent": "5"}},
            "confirmed",
            "BD-941",
        )
    settings_service.change(
        db,
        owner.actor,
        _a(db, owner),
        "pricing.discount_authority",
        {"sales_manager": {"max_percent": "10", "max_amount_minor": {"QAR": 15000}}},
        "confirmed",
        "BD-941",
    )
    view, _contact = _draft(db, rep, discount_minor=10000)  # 5.6 % and QAR 100: within the manager's limits
    quotations.update_draft(
        db,
        rep.actor,
        _a(db, rep),
        view.quote.id,
        valid_until=now_utc().date() + timedelta(days=10),
        customer_note=None,
        internal_note=None,
        discount_reason="Loyal family",
    )
    quotations.submit(db, rep.actor, _a(db, rep), view.quote.id)
    assert _approve(db, manager, view.quote.id).quote.status == "approved"
    big, _c = _draft(db, rep, discount_minor=20000)  # QAR 200: above the amount limit
    quotations.update_draft(
        db,
        rep.actor,
        _a(db, rep),
        big.quote.id,
        valid_until=now_utc().date() + timedelta(days=10),
        customer_note=None,
        internal_note=None,
        discount_reason="Large family",
    )
    quotations.submit(db, rep.actor, _a(db, rep), big.quote.id)
    assert _approve(db, manager, big.quote.id).quote.status == "pending_approval"


def test_promotion_is_a_separate_amount(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    author, approver = managers
    version_id = _live(db, "QA-QAR", *managers)
    _enable(db, "promotions.enabled", True)
    promo = promotions.create(
        db,
        author.actor,
        _a(db, author),
        code="QA-WELCOME",
        name="Welcome",
        description="QAR 50 off",
        terms="New families only",
        kind="amount_off",
        value={"amount_minor": 5000, "currency": "QAR"},
        starts_at=now_utc() - timedelta(days=1),
        ends_at=now_utc() + timedelta(days=30),
        targets=[promotions.TargetIn(version_id)],
        decision_ref="BD-942",
    )
    promotions.submit(db, author.actor, _a(db, author), promo.id)
    promotions.approve(db, approver.actor, _a(db, approver), promo.id)
    promotions.activate(db, approver.actor, _a(db, approver), promo.id)
    rep, manager = people["rep"], people["manager"]
    view, contact = _draft(db, rep, promotion_code="QA-WELCOME")
    line = view.lines[0]
    assert (line.list_total_minor, line.promotion_discount_minor, line.final_total_minor) == (180000, 5000, 175000)
    with pytest.raises(ValidationFailed) as unknown:
        quotations.add_line(db, rep.actor, _a(db, rep), view.quote.id, _entry(db, "QA-QAR", 40), promotion_code="NOPE")
    assert unknown.value.code == "PROMOTION_NOT_OFFERED"
    quotations.update_draft(
        db,
        rep.actor,
        _a(db, rep),
        view.quote.id,
        valid_until=now_utc().date() + timedelta(days=5),
        customer_note=None,
        internal_note=None,
        discount_reason=None,
    )
    submitted = quotations.submit(db, rep.actor, _a(db, rep), view.quote.id)
    assert submitted.needs["reasons"] == ["promotion"] and not submitted.needs["pricing"]
    approved = _approve(db, manager, view.quote.id)
    quotations.issue(db, rep.actor, _a(db, rep), view.quote.id, contact)
    quotations.record_outcome(db, rep.actor, _a(db, rep), view.quote.id, "accepted", "Signed up")
    # max_per_account = 1: the same family cannot use it again
    second, _c = _draft(db, rep)
    assert approved.quote.pricing_snapshot["lines"][0]["promotion"]["code"] == "QA-WELCOME"
    account_id = approved.quote.account_id
    again = quotations.create(db, rep.actor, _a(db, rep), account_id, approved.quote.opportunity_id)
    again = quotations.add_line(
        db, rep.actor, _a(db, rep), again.quote.id, _entry(db, "QA-QAR", 40), promotion_code="QA-WELCOME"
    )
    assert any("already used the promotion" in c for c in again.checks)
    assert second.quote.status == "draft"


def test_issue_checks_recipient_and_price_changes(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager = people["rep"], people["manager"]
    view, contact = _draft(db, rep)
    quote_id = view.quote.id
    quotations.submit(db, rep.actor, _a(db, rep), quote_id)
    _approve(db, manager, quote_id, valid_until=now_utc().date() + timedelta(days=10))
    _other_account, _opp, outsider = _household(db, rep)
    with pytest.raises(Conflict) as wrong:
        quotations.issue(db, rep.actor, _a(db, rep), quote_id, outsider)
    assert any(m.startswith("V-08") for m in wrong.value.extra["missing"])
    quotations.issue(db, rep.actor, _a(db, rep), quote_id, contact)
    # Mixt retires the Qatar price after the quote was issued.
    pricing.retire(db, managers[0].actor, _a(db, managers[0]), _version_id(db, "QA-QAR"), "price change (test)")
    with pytest.raises(Conflict) as reconfirm:
        quotations.record_outcome(db, rep.actor, _a(db, rep), quote_id, "accepted", "Parent agreed")
    assert reconfirm.value.code == "PRICE_CHANGE_RECONFIRM"
    done = quotations.record_outcome(
        db, rep.actor, _a(db, rep), quote_id, "accepted", "Honoured at the quoted price", price_change_reconfirmed=True
    )
    assert done.quote.status == "accepted" and "reconfirmed" in (done.quote.outcome_note or "")
    assert done.quote.pricing_snapshot["totals"]["total"] == "QAR 1,800"  # the issued quote never changes


def test_revisions_supersede_and_reprice(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager = people["rep"], people["manager"]
    view, _contact = _draft(db, rep)
    quotations.submit(db, rep.actor, _a(db, rep), view.quote.id)
    _approve(db, manager, view.quote.id, valid_until=now_utc().date() + timedelta(days=10))
    revised, dropped = quotations.revise(db, rep.actor, _a(db, rep), view.quote.id)
    assert dropped == [] and revised.quote.revision_no == 2 and revised.quote.status == "draft"
    assert revised.quote.quote_number == view.quote.quote_number and revised.quote.parent_quotation_id == view.quote.id
    assert [line.list_total_minor for line in revised.lines] == [180000]
    old = quotations.get(db, _a(db, rep), view.quote.id).quote
    assert old.status == "superseded" and old.snapshot_hash  # kept, frozen
    pricing.retire(db, managers[0].actor, _a(db, managers[0]), _version_id(db, "QA-QAR"), "no longer sold")
    with pytest.raises(Conflict) as stale:
        quotations.submit(db, rep.actor, _a(db, rep), revised.quote.id)
    assert any(m.startswith("V-01") for m in stale.value.extra["missing"])


def test_frozen_quotations_never_change_in_the_database(
    db: Session, owner_db: Session, managers: Any, people: dict[str, TestUser]
) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager = people["rep"], people["manager"]
    view, _contact = _draft(db, rep)
    quotations.submit(db, rep.actor, _a(db, rep), view.quote.id)
    _approve(db, manager, view.quote.id, valid_until=now_utc().date() + timedelta(days=10))
    db.flush()
    for sql, fragment in (
        ("UPDATE quotations SET total_minor = 1, subtotal_minor = 1 WHERE id = :q", "never changes"),
        ("UPDATE quotation_lines SET discount_minor = 0 WHERE quotation_id = :q", "only change while"),
        ("DELETE FROM quotations WHERE id = :q", "never deleted"),
    ):
        with pytest.raises(DBAPIError) as info, db.begin_nested():
            db.execute(text(sql), {"q": view.quote.id})
        assert fragment in str(info.value)


def test_expiry_and_cancellation(db: Session, managers: Any, people: dict[str, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    rep, manager = people["rep"], people["manager"]
    view, contact = _draft(db, rep)
    quotations.submit(db, rep.actor, _a(db, rep), view.quote.id)
    _approve(db, manager, view.quote.id, valid_until=now_utc().date())
    quotations.issue(db, rep.actor, _a(db, rep), view.quote.id, contact)
    assert quotations.expire_due(db) == 0  # still valid today
    assert quotations.expire_due(db, now_utc().date() + timedelta(days=1)) == 1  # the worker, a day later
    with pytest.raises(Conflict):
        quotations.record_outcome(db, rep.actor, _a(db, rep), view.quote.id, "declined", "Too expensive")
    other, _c = _draft(db, rep)
    assert (
        quotations.cancel(db, rep.actor, _a(db, rep), other.quote.id, "Customer chose a trial first").quote.status
        == "cancelled"
    )
    with pytest.raises(Conflict):
        quotations.cancel(db, rep.actor, _a(db, rep), other.quote.id, "again please")
    with pytest.raises(ValidationFailed):
        quotations.update_draft(
            db,
            rep.actor,
            _a(db, rep),
            _draft(db, rep)[0].quote.id,
            valid_until=date(2020, 1, 1),
            customer_note=None,
            internal_note=None,
            discount_reason=None,
        )


def test_quotations_api(as_user: Any, app_factory: Any, db: Session, managers: Any) -> None:
    _live(db, "QA-QAR", *managers)
    rep, rep_user = as_user([("sales_rep", None)])
    household = rep.post("/api/v1/crm/accounts", json={"display_name": "API quote family"}).json()
    rep.post(
        f"/api/v1/crm/accounts/{household['id']}/market-confirmation",
        json={"market_id": str(market_id(db, "QA")), "note": "Lives in Doha"},
        headers={"If-Match": f'"{household["version"]}"'},
    )
    opp = pipeline.create_opportunity_system(db, rep_user.actor, uuid.UUID(household["id"]), "API deal", rep_user.id)
    contact = rep.post(
        f"/api/v1/crm/accounts/{household['id']}/contacts", json={"role": "guardian", "first_name": "Noor"}
    ).json()
    created = rep.post("/api/v1/quotations", json={"account_id": household["id"], "opportunity_id": str(opp.id)})
    assert created.status_code == 201
    qid = created.json()["id"]
    options = rep.get(f"/api/v1/accounts/{household['id']}/pricing/options", params={"quantity": "60"}).json()
    entry_id = str(_entry(db, "QA-QAR", 60))
    assert options["options"][0]["package_total_display"] == "QAR 3,180"
    line = rep.post(f"/api/v1/quotations/{qid}/lines", json={"entry_id": entry_id})
    assert line.status_code == 201 and line.json()["total_display"] == "QAR 3,180"
    assert rep.post(f"/api/v1/quotations/{qid}/submit").json()["status"] == "pending_approval"
    manager = sign_in(app_factory(), db, make_user(db, [("sales_manager", None)]))
    inbox = manager.get("/api/v1/quotations/approvals").json()
    assert qid in {q["id"] for q in inbox}
    sent_back = manager.post(f"/api/v1/quotations/{qid}/send-back", json={"reason": "Add the validity date"}).json()
    assert sent_back["status"] == "draft"
    rep.patch(f"/api/v1/quotations/{qid}", json={"valid_until": (now_utc().date() + timedelta(days=7)).isoformat()})
    rep.post(f"/api/v1/quotations/{qid}/submit")
    approved = manager.post(f"/api/v1/quotations/{qid}/approve", json={"capacity": "sales"}).json()
    assert approved["status"] == "approved" and approved["snapshot_hash"]
    document = rep.get(f"/api/v1/quotations/{qid}/pdf")
    assert document.status_code == 200 and document.headers["content-type"] == "application/pdf"
    assert document.content.startswith(b"%PDF")
    issued = rep.post(f"/api/v1/quotations/{qid}/issue", json={"contact_id": contact["id"]}).json()
    assert issued["status"] == "issued"
    listed = rep.get(f"/api/v1/accounts/{household['id']}/quotations").json()
    assert [q["status"] for q in listed] == ["issued"]
    revised = rep.post(f"/api/v1/quotations/{qid}/revise").json()
    assert revised["quotation"]["revision_no"] == 2 and revised["dropped"] == []
    outcome = rep.post(f"/api/v1/quotations/{qid}/outcome", json={"outcome": "accepted", "note": "x"})
    assert outcome.status_code == 409  # revision 1 was superseded by the revision
    draft_pdf = rep.get(f"/api/v1/quotations/{revised['quotation']['id']}/pdf")
    assert draft_pdf.json()["code"] == "NOT_APPROVED"
    assert Decimal(revised["quotation"]["lines"][0]["quantity"]) == 60


def test_pdf_shows_promotions_benefits_and_terms_from_the_snapshot_only() -> None:
    snapshot = {
        "quote_number": "Q-000123",
        "revision_no": 2,
        "customer": {"account_number": "MX-000042", "name": "Haddad family <test>"},
        "market": {"country": "QA", "name": "Qatar"},
        "currency": "QAR",
        "valid_until": "2026-12-01",
        "tax_treatment": "exclusive",
        "lines": [
            {
                "display_name": "30h",
                "quantity": "30",
                "unit_type": "hour",
                "list_total": "QAR 1,800",
                "final_total": "QAR 1,750",
                "promotion": {"name": "Welcome", "terms": "New families only", "code": "W"},
                "promotion_discount_minor": 5000,
                "bonus_units": None,
                "discount_minor": 0,
                "benefits": ["Recorded sessions"],
            },
            {
                "display_name": "15 classes",
                "quantity": "15",
                "unit_type": "class",
                "list_total": "QAR 1,050",
                "final_total": "QAR 1,000",
                "promotion": {"name": "Bonus", "terms": None, "code": "B"},
                "promotion_discount_minor": 0,
                "bonus_units": "2",
                "discount_minor": 5000,
                "benefits": [],
            },
        ],
        "totals": {"total": "QAR 2,750"},
        "customer_note": "Thank you & welcome",
    }
    document = pdf.render(snapshot, "a" * 64, "Aisha")
    assert document.startswith(b"%PDF") and document == pdf.render(snapshot, "a" * 64, "Aisha")
    assert pdf.render(snapshot, "b" * 64) != document  # the fingerprint is part of the document
