"""Phase 2b pricing: rule language and tester, eligibility and minimum purchase, confidential customer
pricing, promotions kept apart from list prices, and pricing sheet imports."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR
from mixt.core.errors import Conflict, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.engagement import service as engagement
from mixt.modules.identity.access import load_access
from mixt.modules.pricing import imports, promotions, resolution, rule_service, rules, special
from mixt.modules.pricing import service as pricing
from mixt.modules.pricing.models import PriceBook, PriceBookEntry, PriceBookMarketAssignment, PriceBookVersion
from mixt.modules.settings import service as settings_service
from mixt.modules.settings.models import SystemSetting
from tests.conftest import TestUser, make_user, market_id
from tests.test_pricing import _customer, _live, _version_id

ELIGIBLE_NEW = {"condition": {"fact": "account.is_new_customer", "op": "eq", "value": True}}


@pytest.fixture
def managers(db: Session) -> tuple[TestUser, TestUser]:
    return make_user(db, [("pricing_manager", None)]), make_user(db, [("pricing_manager", None)])


def _acc(db: Session, user: TestUser) -> Any:
    return load_access(db, user.actor)


def _approved_rule(db: Session, managers: tuple[TestUser, TestUser], code: str, kind: str, definition: Any) -> Any:
    author, approver = managers
    rule = rule_service.create_rule(
        db, author.actor, _acc(db, author), code, f"Rule {code}", kind, definition, None, "BD-920"
    )
    return rule_service.approve_rule(db, approver.actor, _acc(db, approver), rule.id)


def _assignment(db: Session, code: str, country: str) -> PriceBookMarketAssignment:
    row = db.scalar(
        select(PriceBookMarketAssignment)
        .join(PriceBook, PriceBook.id == PriceBookMarketAssignment.price_book_id)
        .where(PriceBook.code == code, PriceBookMarketAssignment.market_id == market_id(db, country))
    )
    assert row is not None
    return row


def _enable(db: Session, key: str, value: Any) -> None:
    """Test-only: set a dual-approval setting directly (the approval workflow is not built yet)."""
    db.add(
        SystemSetting(
            key=key,
            scope_type="global",
            scope_id=None,
            value={"v": value},
            status="confirmed",
            decision_ref="BD-999",
            updated_by=SYSTEM_ACTOR.principal_id,
        )
    )
    db.flush()


# ------------------------------------------------------------------------------------- rule language


@pytest.mark.parametrize(
    ("condition", "fragment"),
    [
        ({"fact": "account.colour", "op": "eq", "value": "red"}, "unknown fact"),
        ({"fact": "students.count", "op": "in", "value": ["1"]}, "is a number"),
        ({"fact": "account.is_new_customer", "op": "eq", "value": "yes"}, "true or false"),
        ({"fact": "students.count", "op": "between", "value": [5, 1]}, "low <= high"),
        ({"fact": "today", "op": "gte", "value": "next week"}, "not a valid date"),
        ({"fact": "account.lead_source", "op": "in", "value": []}, "non-empty list"),
        ({"all": []}, "non-empty list"),
        ({"maybe": 1}, "use all / any / not"),
        (
            {"not": {"not": {"not": {"not": {"not": {"not": {"fact": "today", "op": "eq", "value": "2026-01-01"}}}}}}},
            "nested too deeply",
        ),
    ],
)
def test_invalid_rules_are_refused(condition: Any, fragment: str) -> None:
    problems = rules.validate_condition(condition)
    assert any(fragment in p for p in problems), problems


def test_rule_evaluation_with_trace() -> None:
    condition = {
        "all": [
            {"fact": "account.market", "op": "in", "value": ["IE", "GB"]},
            {
                "any": [
                    {"fact": "account.tags", "op": "contains", "value": "sibling"},
                    {"fact": "students.count", "op": "gte", "value": 2},
                ]
            },
            {"not": {"fact": "account.lead_source", "op": "eq", "value": "import"}},
            {"fact": "today", "op": "between", "value": ["2026-01-01", "2026-12-31"]},
            {"fact": "students.curricula", "op": "exists", "value": True},
        ]
    }
    assert rules.validate_condition(condition) == []
    facts = {
        "account.market": "IE",
        "account.tags": [],
        "students.count": 2,
        "account.lead_source": "website_form",
        "today": date(2026, 11, 10),
        "students.curricula": ["IRISH"],
    }
    outcome = rules.evaluate(condition, facts)
    assert outcome.result is True
    assert "students.count = 2; gte 2: yes" in "\n".join(outcome.trace)
    assert rules.evaluate(condition, {**facts, "students.count": 1}).result is False
    assert rules.evaluate(condition, {**facts, "account.market": None}).result is False


def test_rule_definitions_by_kind() -> None:
    rules.validate_definition("eligibility", ELIGIBLE_NEW)
    rules.validate_definition("minimum_purchase", {"condition": None, "min_quantity": 60})
    for kind, definition in (
        ("eligibility", {"condition": ELIGIBLE_NEW["condition"], "extra": 1}),
        ("minimum_purchase", {"condition": None, "min_quantity": 0}),
        ("minimum_purchase", {"min_quantity": 5}),
        ("surcharge", {}),
    ):
        with pytest.raises(rules.RuleInvalid):
            rules.validate_definition(kind, definition)


# ------------------------------------------------------------------------------------- rule lifecycle


def test_rules_are_versioned_and_approved_by_someone_else(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    author, approver = managers
    rule = rule_service.create_rule(
        db, author.actor, _acc(db, author), "NEW-ONLY", "New", "eligibility", ELIGIBLE_NEW, None, None
    )
    with pytest.raises(ValidationFailed) as invalid:
        rule_service.create_rule(
            db, author.actor, _acc(db, author), "BAD", "Bad", "eligibility", {"condition": {"x": 1}}, None, None
        )
    assert invalid.value.code == "RULE_INVALID" and invalid.value.extra["missing"]
    with pytest.raises(PermissionDenied):
        rule_service.approve_rule(db, author.actor, _acc(db, author), rule.id)
    with pytest.raises(ValidationFailed) as no_ref:
        rule_service.approve_rule(db, approver.actor, _acc(db, approver), rule.id)
    assert no_ref.value.code == "DECISION_REF_REQUIRED"
    rule_service.update_draft(db, author.actor, _acc(db, author), rule.id, "New customers", ELIGIBLE_NEW, "d", "BD-920")
    approved = rule_service.approve_rule(db, approver.actor, _acc(db, approver), rule.id)
    assert approved.status == "approved"
    with pytest.raises(Conflict):
        rule_service.update_draft(db, author.actor, _acc(db, author), rule.id, "x", ELIGIBLE_NEW, None, None)
    second = rule_service.create_rule(
        db, author.actor, _acc(db, author), "NEW-ONLY", "New v2", "eligibility", ELIGIBLE_NEW, None, None
    )
    assert second.rule_version == 2 and approved.rule_version == 1


def test_approved_rules_never_change_in_the_database(owner_db: Session) -> None:
    owner_db.execute(
        text(
            "INSERT INTO pricing_rules (id, code, name, kind, definition, status, created_by, approved_by) "
            "VALUES (gen_random_uuid(), 'FIXED', 'x', 'eligibility', '{\"condition\": null}', 'approved', :a, :b)"
        ),
        {"a": SYSTEM_ACTOR.principal_id, "b": make_user(owner_db).user.principal_id},
    )
    with pytest.raises(DBAPIError) as info, owner_db.begin_nested():
        owner_db.execute(text("UPDATE pricing_rules SET definition = '{}' WHERE code = 'FIXED'"))
    assert "never changes" in str(info.value)
    with pytest.raises(DBAPIError) as gone, owner_db.begin_nested():
        owner_db.execute(text("DELETE FROM pricing_rules WHERE code = 'FIXED'"))
    assert "never deleted" in str(gone.value)


def test_rule_tester_explains_the_decision(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    rule = _approved_rule(
        db,
        managers,
        "SIBLINGS",
        "eligibility",
        {
            "condition": {
                "all": [
                    {"fact": "account.tags", "op": "contains", "value": "Sibling offer"},
                    {"fact": "account.market", "op": "eq", "value": "QA"},
                ]
            }
        },
    )
    seller = make_user(db, [("sales_manager", None)])
    account = _customer(db, "QA", seller)
    owner = make_user(db, [("owner", None)])
    tag = engagement.create_tag(db, owner.actor, _acc(db, owner), "Sibling offer")
    engagement.tag_account(db, owner.actor, _acc(db, owner), account, tag.id)
    outcome = rule_service.try_rule(db, _acc(db, owner), rule.id, account)
    assert outcome.result is True
    assert outcome.facts["account.market"] == "QA" and outcome.facts["account.is_new_customer"] is True
    assert outcome.facts["account.tags"] == ["Sibling offer"] and outcome.facts["students.count"] == 0


def test_eligibility_and_minimum_purchase_in_resolution(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    account = _customer(db, "QA")
    assignment = _assignment(db, "QA-QAR", "QA")
    author = managers[0]
    returning = _approved_rule(
        db,
        managers,
        "RETURNING",
        "eligibility",
        {"condition": {"fact": "account.is_new_customer", "op": "eq", "value": False}},
    )
    rule_service.attach_rule(db, author.actor, _acc(db, author), assignment.id, "eligibility", returning.id)
    assert resolution.PricingUnavailable  # a new customer is not eligible for this book
    with pytest.raises(resolution.PricingUnavailable) as none:
        resolution.resolve_options(db, account)
    assert none.value.code == "NO_APPROVED_PRICING_FOR_MARKET"
    rule_service.attach_rule(db, author.actor, _acc(db, author), assignment.id, "eligibility", None)
    minimum = _approved_rule(db, managers, "MIN-30", "minimum_purchase", {"condition": None, "min_quantity": 30})
    with pytest.raises(ValidationFailed) as kind:
        rule_service.attach_rule(db, author.actor, _acc(db, author), assignment.id, "eligibility", minimum.id)
    assert kind.value.code == "WRONG_RULE_KIND"
    rule_service.attach_rule(db, author.actor, _acc(db, author), assignment.id, "minimum_purchase", minimum.id)
    found = resolution.resolve_options(db, account)
    assert [int(o.quantity) for o in found.options] == [30, 40, 60, 100, 150, 200]
    with pytest.raises(resolution.PricingUnavailable) as below:
        resolution.resolve_options(db, account, quantity=Decimal(20))
    assert below.value.code == "BELOW_MINIMUM_PURCHASE" and below.value.extra["minimums"] == ["QA-QAR: at least 30"]
    with pytest.raises(Conflict) as in_use:
        rule_service.retire_rule(db, managers[1].actor, _acc(db, managers[1]), minimum.id)
    assert in_use.value.code == "RULE_IN_USE"


# ------------------------------------------------------------------------------------- imports


CSV_OK = (
    "price_book_code,currency,plan_type,tier_label,audience,unit_type,quantity,package_total\n"
    "QA-QAR-FAMILY,QAR,standard,Family,restricted,hour,30,1650\n"
    "QA-QAR-FAMILY,QAR,standard,Family,restricted,hour,60,3000\n"
    "QA-QAR,QAR,standard,,public,hour,15,1050\n"
    "QA-QAR,QAR,standard,,public,hour,20,1350\n"
    "QA-QAR,QAR,standard,,public,hour,250,9000\n"
)


def test_import_checks_every_row(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    user = managers[0]
    bad = (
        "price_book_code,currency,plan_type,unit_type,quantity,package_total\n"
        "uk lower,GBP,standard,hour,10,100\n"
        "NEW-BOOK,XXX,standard,hour,10,100\n"
        "NEW-BOOK-2,GBP,standard,hour,10,100.005\n"
        "NEW-BOOK-2,GBP,standard,hour,10,120\n"
        "QA-QAR,GBP,standard,hour,15,1050\n"
        "QA-QAR,QAR,premium,hour,15,1050\n"
        "NEW-BOOK-3,GBP,custom,minute,-1,abc\n"
    )
    batch = imports.validate(db, user.actor, _acc(db, user), "bad.csv", bad.encode())
    _batch, rows = imports.get_batch(db, _acc(db, user), batch.id)
    errors = {r.row_no: " ".join(r.errors) for r in rows}
    assert batch.status == "invalid" and batch.error_count == 6
    assert "capital letters" in errors[2] and "not a known ISO currency" in errors[3]
    assert "more decimal places" in errors[4] and errors[5] == ""
    assert "never changes" in errors[6] and "plan_type: QA-QAR is standard" in errors[7]
    assert all(word in errors[8] for word in ("plan_type", "unit_type", "quantity"))
    with pytest.raises(Conflict):
        imports.apply(
            db,
            user.actor,
            _acc(db, user),
            batch.id,
            change_type="price_change",
            source_document="x sheet",
            source_received_on=date(2026, 11, 10),
            change_summary="should not apply",
        )
    with pytest.raises(ValidationFailed) as columns:
        imports.validate(db, user.actor, _acc(db, user), "x.csv", b"code,total\nA,1\n")
    assert columns.value.code == "TEMPLATE_COLUMNS_MISSING"


def test_import_report_and_apply_as_drafts(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    user = managers[0]
    before = [(e.package_code, e.package_total_minor) for e in pricing.entries_of(db, _version_id(db, "QA-QAR"))]
    batch = imports.validate(db, user.actor, _acc(db, user), "sheet.csv", CSV_OK.encode())
    assert batch.status == "validated", imports.get_batch(db, _acc(db, user), batch.id)[1]
    report = {b["code"]: b for b in batch.report["books"]}
    assert report["QA-QAR-FAMILY"]["diff"]["is_new"] is True and report["QA-QAR-FAMILY"]["audience"] == "restricted"
    qatar = report["QA-QAR"]["diff"]
    assert qatar["compared_with"] == "version 1 (draft)"
    assert qatar["changed"] == [{"quantity": "20", "from_minor": 130000, "to_minor": 135000}]
    assert qatar["added"] == [{"quantity": "250", "total_minor": 900000}]
    assert [r["quantity"] for r in qatar["removed"]] == ["30", "40", "60", "100", "150", "200"]
    assert qatar["unchanged"] == 1
    imports.apply(
        db,
        user.actor,
        _acc(db, user),
        batch.id,
        change_type="price_change",
        source_document="Qatar sheet (test)",
        source_received_on=date(2026, 11, 10),
        change_summary="New Qatar figures (test)",
    )
    family = db.scalar(select(PriceBook).where(PriceBook.code == "QA-QAR-FAMILY"))
    assert family is not None and family.audience == "restricted" and family.tier_label == "Family"
    assert (
        db.scalar(select(PriceBookMarketAssignment).where(PriceBookMarketAssignment.price_book_id == family.id)) is None
    )
    v2 = db.get(PriceBookVersion, _version_id(db, "QA-QAR", 2))
    assert v2 is not None and v2.status == "draft" and v2.change_type == "price_change" and v2.figures_locked
    assert v2.unit_definition_ref is None  # Mixt confirms the unit before activation (G-04)
    assert [
        (e.package_code, e.package_total_minor) for e in pricing.entries_of(db, _version_id(db, "QA-QAR"))
    ] == before
    with pytest.raises(Conflict):
        imports.apply(
            db,
            user.actor,
            _acc(db, user),
            batch.id,
            change_type="price_change",
            source_document="again",
            source_received_on=date(2026, 11, 10),
            change_summary="applied twice?",
        )


def test_import_as_correction_closes_the_draft_it_corrects(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    user = managers[0]
    sheet = "price_book_code,currency,plan_type,unit_type,quantity,package_total\nMY-MYR,MYR,standard,hour,15,1170\n"
    batch = imports.validate(db, user.actor, _acc(db, user), "my.csv", sheet.encode())
    imports.apply(
        db,
        user.actor,
        _acc(db, user),
        batch.id,
        change_type="correction",
        source_document="Malaysia sheet",
        source_received_on=date(2026, 11, 10),
        change_summary="Malaysia corrected set (test)",
    )
    v1, v2 = db.get(PriceBookVersion, _version_id(db, "MY-MYR")), db.get(PriceBookVersion, _version_id(db, "MY-MYR", 2))
    assert v1 is not None and v2 is not None
    assert v1.status == "rejected" and v2.change_type == "correction" and v2.supersedes_version_id == v1.id
    discarded = imports.validate(db, user.actor, _acc(db, user), "my.csv", sheet.encode())
    assert imports.discard(db, user.actor, _acc(db, user), discarded.id).status == "discarded"


# ------------------------------------------------------------------------------------- special pricing


def _special_book(db: Session, managers: tuple[TestUser, TestUser]) -> PriceBook:
    """A restricted QAR book, imported, assigned to Qatar and activated through the normal checklist."""
    user, second = managers
    sheet = (
        "price_book_code,currency,plan_type,audience,unit_type,quantity,package_total\n"
        "QA-QAR-FAMILY,QAR,standard,restricted,hour,30,1650\n"
        "QA-QAR-FAMILY,QAR,standard,restricted,hour,60,3000\n"
    )
    batch = imports.validate(db, user.actor, _acc(db, user), "family.csv", sheet.encode())
    imports.apply(
        db,
        user.actor,
        _acc(db, user),
        batch.id,
        change_type="price_change",
        source_document="Family sheet",
        source_received_on=date(2026, 11, 10),
        change_summary="Family pricing (test)",
    )
    book = db.scalar(select(PriceBook).where(PriceBook.code == "QA-QAR-FAMILY"))
    assert book is not None
    pricing.assign_market(db, user.actor, _acc(db, user), book.id, market_id(db, "QA"), "BD-921", "test")
    version_id = _version_id(db, "QA-QAR-FAMILY")
    pricing.confirm_unit_definition(db, user.actor, _acc(db, user), version_id, "BD-922")
    pricing.confirm_figures(db, user.actor, _acc(db, user), version_id, "BD-923", "Family figures confirmed (test)")
    pricing.set_tax_treatment(db, user.actor, _acc(db, user), version_id, "inclusive", "BD-902")
    pricing.submit(db, user.actor, _acc(db, user), version_id)
    pricing.approve(db, second.actor, _acc(db, second), version_id)
    owner = make_user(db, [("owner", None)])
    pricing.approve(db, owner.actor, _acc(db, owner), version_id)
    pricing.activate(db, user.actor, _acc(db, user), version_id)
    return book


def test_confidential_pricing_only_for_its_customer(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    book = _special_book(db, managers)
    _live(db, "QA-QAR", *managers)
    seller = make_user(db, [("sales_manager", None)])
    family, neighbour = _customer(db, "QA", seller), _customer(db, "QA", seller)
    # A restricted book is never offered without an approved assignment.
    assert "QA-QAR-FAMILY" not in {
        o.price_book_code for o in resolution.resolve_options(db, family, include_special=True).options
    }
    with pytest.raises(ValidationFailed) as short:
        special.request(db, seller.actor, _acc(db, seller), family, book.id, "short", None, None)
    assert short.value.code == "REASON_REQUIRED"
    pending = special.request(
        db, seller.actor, _acc(db, seller), family, book.id, "Three siblings, agreed with management", None, None
    )
    with pytest.raises(PermissionDenied):
        special.approve(db, seller.actor, _acc(db, seller), pending.assignment.id)
    approver = managers[0]
    approver_access = _acc(db, approver)
    owner = make_user(db, [("owner", None)])
    special.approve(db, owner.actor, _acc(db, owner), pending.assignment.id)
    assert approver_access  # pricing managers may approve too; the owner did here
    with_special = resolution.resolve_options(db, family, include_special=True)
    assert {o.price_book_code for o in with_special.options} == {"QA-QAR-FAMILY"}
    assert all(o.special_assignment_id == pending.assignment.id for o in with_special.options)
    # People without pricing.special.view, and every other customer, never see it.
    assert {o.price_book_code for o in resolution.resolve_options(db, family).options} == {"QA-QAR"}
    assert {o.price_book_code for o in resolution.resolve_options(db, neighbour, include_special=True).options} == {
        "QA-QAR"
    }
    rep = make_user(db, [("sales_rep", None)])
    own = _customer(db, "QA", rep)  # the rep's own customer: visible, but confidential pricing is not
    with pytest.raises(PermissionDenied):
        special.list_for_account(db, _acc(db, rep), own)
    special.close(db, owner.actor, _acc(db, owner), pending.assignment.id, "revoke", "Siblings left")
    assert {o.price_book_code for o in resolution.resolve_options(db, family, include_special=True).options} == {
        "QA-QAR"
    }


def test_special_pricing_rules(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    book = _special_book(db, managers)
    seller = make_user(db, [("sales_manager", None)])
    owner = make_user(db, [("owner", None)])
    uae = _customer(db, "AE", seller)
    with pytest.raises(ValidationFailed) as other_market:
        special.request(db, seller.actor, _acc(db, seller), uae, book.id, "Wrong market attempt", None, None)
    assert other_market.value.code == "NOT_A_SPECIAL_BOOK"
    qatar = _customer(db, "QA", seller)
    public = db.scalar(select(PriceBook).where(PriceBook.code == "QA-QAR"))
    assert public is not None
    with pytest.raises(ValidationFailed):
        special.request(db, seller.actor, _acc(db, seller), qatar, public.id, "Public book is not special", None, None)
    start = now_utc() - timedelta(days=2)
    short = special.request(
        db,
        seller.actor,
        _acc(db, seller),
        qatar,
        book.id,
        "Trial month for the family",
        start,
        start + timedelta(days=1),
    )
    special.approve(db, owner.actor, _acc(db, owner), short.assignment.id)
    assert special.active_books(db, qatar, now_utc()) == {}  # its validity has ended
    listed = special.list_for_account(db, _acc(db, owner), qatar)
    assert listed[0].assignment.status == "expired"
    rejected = special.request(db, seller.actor, _acc(db, seller), qatar, book.id, "Another request here", None, None)
    assert (
        special.close(
            db, owner.actor, _acc(db, owner), rejected.assignment.id, "reject", "Not justified"
        ).assignment.status
        == "rejected"
    )
    with pytest.raises(Conflict):
        special.close(db, owner.actor, _acc(db, owner), rejected.assignment.id, "revoke", "again")


# ------------------------------------------------------------------------------------- promotions


def _promotion(db: Session, user: TestUser, version_id: uuid.UUID, **kw: Any) -> Any:
    values: dict[str, Any] = {
        "code": "SUMMER-QA",
        "name": "Summer offer",
        "description": "Two extra hours with any package this summer",
        "terms": None,
        "kind": "bonus_units",
        "value": {"units": 2},
        "starts_at": now_utc() - timedelta(days=1),
        "ends_at": now_utc() + timedelta(days=30),
        "targets": [promotions.TargetIn(version_id)],
        "decision_ref": "BD-930",
    }
    values.update(kw)
    return promotions.create(db, user.actor, _acc(db, user), **values)


def test_promotion_validation(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    user = managers[0]
    version_id = _version_id(db, "QA-QAR")
    cases = [
        ({"ends_at": now_utc() - timedelta(days=2)}, "END_BEFORE_START"),
        ({"starts_at": now_utc() - timedelta(days=9), "ends_at": now_utc() - timedelta(days=1)}, "ALREADY_ENDED"),
        ({"kind": "amount_off", "value": {"amount_minor": 1000, "currency": "GBP"}}, "CURRENCY_MISMATCH"),
        ({"kind": "amount_off", "value": {"amount_minor": 105000, "currency": "QAR"}}, "AMOUNT_TOO_LARGE"),
        ({"kind": "percent_off", "value": {"percent": "120"}}, "INVALID_PROMOTION_VALUE"),
        ({"kind": "percent_off", "value": {"amount": 1}}, "INVALID_PROMOTION_VALUE"),
        ({"targets": []}, "TARGETS_REQUIRED"),
    ]
    for overrides, code in cases:
        with pytest.raises(ValidationFailed) as info:
            _promotion(db, user, version_id, **overrides)
        assert info.value.code == code, overrides


def test_promotions_are_separate_from_list_prices(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    author, approver = managers
    version_id = _live(db, "QA-QAR", *managers)
    snapshot = [
        (e.id, e.package_code, e.quantity, e.package_total_minor)
        for e in db.scalars(select(PriceBookEntry).order_by(PriceBookEntry.id))
    ]
    promo = _promotion(db, author, version_id, kind="amount_off", value={"amount_minor": 5000, "currency": "QAR"})
    promotions.submit(db, author.actor, _acc(db, author), promo.id)
    with pytest.raises(PermissionDenied):
        promotions.approve(db, author.actor, _acc(db, author), promo.id)
    promotions.approve(db, approver.actor, _acc(db, approver), promo.id)
    with pytest.raises(Conflict) as switched_off:
        promotions.activate(db, approver.actor, _acc(db, approver), promo.id)
    assert switched_off.value.code == "PROMOTION_CANNOT_START"
    assert "promotions.enabled" in " ".join(switched_off.value.extra["missing"])
    _enable(db, "promotions.enabled", True)
    promotions.activate(db, approver.actor, _acc(db, approver), promo.id)
    account = _customer(db, "QA")
    found = resolution.resolve_options(db, account, quantity=Decimal(15))
    option = found.options[0]
    assert option.package_total_minor == 105000  # the list price is untouched...
    assert [(p.code, p.promotional_total_minor) for p in option.promotions] == [
        ("SUMMER-QA", 100000)
    ]  # ...offer is separate
    promotions.cancel(db, approver.actor, _acc(db, approver), promo.id, "Ended early")
    assert resolution.resolve_options(db, account, quantity=Decimal(15)).options[0].promotions == ()
    after = [
        (e.id, e.package_code, e.quantity, e.package_total_minor)
        for e in db.scalars(select(PriceBookEntry).order_by(PriceBookEntry.id))
    ]
    assert after == snapshot  # byte-for-byte: no standard figure changed


def test_percentages_need_a_rounding_rule(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    author, approver = managers
    version_id = _live(db, "QA-QAR", *managers)
    _enable(db, "promotions.enabled", True)
    promo = _promotion(db, author, version_id, code="TEN-OFF", kind="percent_off", value={"percent": "10"})
    promotions.submit(db, author.actor, _acc(db, author), promo.id)
    promotions.approve(db, approver.actor, _acc(db, approver), promo.id)
    assert promotions.activation_problems(db, promo) == [
        "Percentage offers are not allowed yet (setting pricing.discounts.mode, Q-PRC-12)"
    ]
    owner = make_user(db, [("owner", None)])

    settings_service.change(
        db, owner.actor, _acc(db, owner), "pricing.discounts.mode", "percent_allowed", "confirmed", "BD-931"
    )
    odd = _promotion(db, author, version_id, code="SEVEN-OFF", kind="percent_off", value={"percent": "33.33"})
    promotions.submit(db, author.actor, _acc(db, author), odd.id)
    promotions.approve(db, approver.actor, _acc(db, approver), odd.id)
    assert any("rounding rule" in p for p in promotions.activation_problems(db, odd))
    activated = promotions.activate(db, approver.actor, _acc(db, approver), promo.id)
    assert activated.status == "active"
    offer = resolution.resolve_options(db, _customer(db, "QA"), quantity=Decimal(20)).options[0].promotions[0]
    assert offer.promotional_total_minor == 117000  # 130000 less 10 %, exact


def test_promotions_expire_and_respect_eligibility(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    author, approver = managers
    version_id = _live(db, "QA-QAR", *managers)
    _enable(db, "promotions.enabled", True)
    returning = _approved_rule(
        db,
        managers,
        "RETURN",
        "eligibility",
        {"condition": {"fact": "account.is_new_customer", "op": "eq", "value": False}},
    )
    promo = _promotion(db, author, version_id, eligibility_rule_id=returning.id)
    promotions.submit(db, author.actor, _acc(db, author), promo.id)
    promotions.approve(db, approver.actor, _acc(db, approver), promo.id)
    promotions.activate(db, approver.actor, _acc(db, approver), promo.id)
    account = _customer(db, "QA")
    assert resolution.resolve_options(db, account).options[0].promotions == ()  # a new customer is not eligible
    later = now_utc() + timedelta(days=31)
    assert promotions.expire_due(db, later) == 1
    db.refresh(promo)
    assert promo.status == "expired"


def test_submitted_promotions_never_change(owner_db: Session, db: Session) -> None:
    user = make_user(owner_db, [("pricing_manager", None)])
    promo = _promotion(owner_db, user, _version_id(owner_db, "QA-QAR"))
    promotions.submit(owner_db, user.actor, load_access(owner_db, user.actor), promo.id)
    with pytest.raises(DBAPIError) as info, owner_db.begin_nested():
        owner_db.execute(text("UPDATE promotions SET value = '{\"units\": 9}' WHERE id = :i"), {"i": promo.id})
    assert "never change" in str(info.value)
    with pytest.raises(DBAPIError) as gone, owner_db.begin_nested():
        owner_db.execute(text("DELETE FROM promotions WHERE id = :i"), {"i": promo.id})
    assert "never deleted" in str(gone.value)


# ------------------------------------------------------------------------------------- API


def test_pricing_admin_api(as_user: Any, db: Session) -> None:
    owner, _ = as_user([("owner", None)])
    template = owner.get("/api/v1/pricing/imports/template")
    assert template.status_code == 200 and template.text.startswith("price_book_code,currency,plan_type")
    uploaded = owner.client.post(
        "/api/v1/pricing/imports",
        files={"file": ("sheet.csv", CSV_OK.encode(), "text/csv")},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert uploaded.status_code == 201 and uploaded.json()["status"] == "validated"
    applied = owner.post(
        f"/api/v1/pricing/imports/{uploaded.json()['id']}/apply",
        json={
            "change_type": "price_change",
            "source_document": "API sheet",
            "source_received_on": "2026-11-10",
            "change_summary": "Uploaded through the API (test)",
        },
    )
    assert applied.json()["status"] == "applied" and len(applied.json()["applied_version_ids"]) == 2
    facts = owner.get("/api/v1/pricing/rules/facts").json()
    assert {
        "fact": "students.count",
        "type": "number",
        "operators": ["between", "eq", "exists", "gte", "lte", "neq"],
    } in facts
    created = owner.post(
        "/api/v1/pricing/rules",
        json={"code": "API-RULE", "name": "API rule", "kind": "eligibility", "definition": ELIGIBLE_NEW},
    )
    assert created.status_code == 201
    bad = owner.post(
        "/api/v1/pricing/rules",
        json={"code": "API-BAD", "name": "API bad", "kind": "eligibility", "definition": {"condition": {"x": 1}}},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "RULE_INVALID" and bad.json()["missing"]
    household = owner.post("/api/v1/crm/accounts", json={"display_name": "Rule test family"}).json()
    tested = owner.post(f"/api/v1/pricing/rules/{created.json()['id']}/test", json={"account_id": household["id"]})
    assert tested.json()["result"] is True and tested.json()["facts"]["account.market"] is None
    assert owner.get("/api/v1/pricing/rules").status_code == 200
    sample = owner.post(
        f"/api/v1/pricing/rules/{created.json()['id']}/evaluate",
        json={"facts": {"account.is_new_customer": False, "today": "2026-11-10"}},
    ).json()
    assert sample["result"] is False and "account.is_new_customer = False" in sample["trace"][0]
    unknown = owner.post(f"/api/v1/pricing/rules/{created.json()['id']}/evaluate", json={"facts": {"colour": "red"}})
    assert unknown.json()["code"] == "UNKNOWN_FACTS"
    promo = owner.post(
        "/api/v1/pricing/promotions",
        json={
            "code": "API-PROMO",
            "name": "API promo",
            "description": "Two bonus hours",
            "kind": "bonus_units",
            "value": {"units": 2},
            "starts_at": now_utc().isoformat(),
            "ends_at": (now_utc() + timedelta(days=5)).isoformat(),
            "targets": [{"price_book_version_id": str(_version_id(db, "QA-QAR"))}],
            "decision_ref": "BD-932",
        },
    )
    assert promo.status_code == 201 and promo.json()["status"] == "draft"
    submitted = owner.post(f"/api/v1/pricing/promotions/{promo.json()['id']}/submit").json()
    assert submitted["status"] == "in_review"
    assert owner.post(f"/api/v1/pricing/promotions/{promo.json()['id']}/approve").json()["code"] == "FOUR_EYES"
    cancelled = owner.post(f"/api/v1/pricing/promotions/{promo.json()['id']}/cancel", json={"reason": "not needed"})
    assert cancelled.json()["status"] == "cancelled"
    listed = owner.get("/api/v1/pricing/promotions").json()
    assert listed[0]["code"] == "API-PROMO"
