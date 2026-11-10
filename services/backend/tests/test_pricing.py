"""Phase 2a pricing: supplied data (golden), database guards, activation gate, lifecycle, corrections,
tier selection and price resolution (docs/04 §18)."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.crm import service as crm
from mixt.modules.identity.access import load_access
from mixt.modules.pricing import resolution
from mixt.modules.pricing import service as pricing
from mixt.modules.pricing.models import (
    BenefitDefinition,
    PackageBenefit,
    PriceBook,
    PriceBookEntry,
    PriceBookMarketAssignment,
    PriceBookVersion,
)
from mixt.modules.settings import service as settings_service
from tests.conftest import TestUser, make_user, market_id

REGISTER = Path(__file__).resolve().parents[3] / "docs" / "05-pricing-data-register.md"
ACCOUNTS = "/api/v1/crm/accounts"


# ------------------------------------------------------------------------- independent register reading


def _register() -> tuple[dict[str, dict[str, str]], dict[str, list[tuple[str, int, str, int, int]]]]:
    """Read docs/05 directly: the summary table and every entries table (an independent transcription)."""
    lines = REGISTER.read_text(encoding="utf-8").splitlines()
    summary: dict[str, dict[str, str]] = {}
    entries: dict[str, list[tuple[str, int, str, int, int]]] = {}
    current: str | None = None
    for line in lines:
        row = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.match(r"^\| \d+ \| `", line):
            code = row[1].strip("`")
            summary[code] = {"currency": row[2], "tier": row[3], "unit": row[4], "entries": row[5], "market": row[6]}
        heading = re.match(r"^### 2\.\d+ `([A-Z0-9-]+)`", line)
        if heading:
            current = heading.group(1)
            entries[current] = []
        elif current and line.startswith("|") and re.match(r"^\d+", row[1] if len(row) > 1 else ""):
            rate = re.sub(r"[^\d.]", "", row[5])
            entries[current].append((row[0], int(row[1]), row[2], int(row[4]), int(Decimal(rate) * 100)))
        elif line.startswith("## 3."):
            current = None
    return summary, entries


def test_register_is_read_completely() -> None:
    summary, entries = _register()
    assert len(summary) == 13 and len(entries) == 13
    assert sum(len(v) for v in entries.values()) == 91
    assert all(int(summary[code]["entries"]) == len(rows) for code, rows in entries.items())


def test_golden_every_supplied_entry_is_stored_exactly(db: Session) -> None:
    summary, register = _register()
    books = {b.code: b for b in db.scalars(select(PriceBook))}
    assert set(books) == set(register)
    for code, rows in register.items():
        book = books[code]
        assert book.currency_code == summary[code]["currency"], code
        assert book.unit_type == summary[code]["unit"].replace("*", "").split(" ")[0], code
        version = db.scalar(select(PriceBookVersion).where(PriceBookVersion.price_book_id == book.id))
        assert version is not None and version.version_no == 1
        stored = [
            (e.display_name, int(e.quantity), book.unit_type, e.package_total_minor, e.derived_unit_rate_minor)
            for e in db.scalars(
                select(PriceBookEntry)
                .where(PriceBookEntry.price_book_version_id == version.id)
                .order_by(PriceBookEntry.quantity)
            )
        ]
        assert stored == rows, code


def test_supplied_versions_are_locked_inactive_drafts(db: Session) -> None:
    versions = list(db.scalars(select(PriceBookVersion)))
    assert len(versions) == 13
    for v in versions:
        assert (v.status, v.figures_locked, v.figures_confirmation, v.tax_treatment) == (
            "draft",
            True,
            "supplied_unverified",
            "unknown",
        )
        assert v.change_type == "initial" and v.source_received_on == date(2026, 11, 9)
        assert v.approved_by is None and v.content_hash is None


def test_usd_books_have_no_market_and_the_us_is_never_one(db: Session) -> None:
    usd = list(db.scalars(select(PriceBook).where(PriceBook.currency_code == "USD")))
    assert {b.code for b in usd} == {"USD-SCHEDULE-A", "USD-SCHEDULE-B"}
    for book in usd:
        assert (
            db.scalar(select(PriceBookMarketAssignment).where(PriceBookMarketAssignment.price_book_id == book.id))
            is None
        )
    countries = db.execute(
        text("SELECT DISTINCT m.country_code FROM price_book_market_assignments a JOIN markets m ON m.id = a.market_id")
    ).scalars()
    assert set(countries) == {"GB", "AE", "SA", "QA", "MY", "IE", "HK"}


def test_supplied_assignments_and_benefits(db: Session) -> None:
    rows = db.execute(
        select(PriceBook.code, PriceBookMarketAssignment).join(
            PriceBookMarketAssignment, PriceBookMarketAssignment.price_book_id == PriceBook.id
        )
    ).all()
    by_code = {row[0]: row[1] for row in rows}
    assert by_code["IE-EUR-SCHEDULE-A"].requires_relationship_confirmation
    assert by_code["IE-EUR-SCHEDULE-B"].requires_relationship_confirmation
    assert not by_code["UK-GBP-TIER-A"].requires_relationship_confirmation
    assert all(a.assignment_status == "confirmed" and a.decision_ref for a in by_code.values())
    attached = db.execute(
        select(PriceBook.code, BenefitDefinition.code, PackageBenefit.status)
        .join(PriceBookVersion, PriceBookVersion.price_book_id == PriceBook.id)
        .join(PackageBenefit, PackageBenefit.price_book_version_id == PriceBookVersion.id)
        .join(BenefitDefinition, BenefitDefinition.id == PackageBenefit.benefit_definition_id)
    ).all()
    assert {code for code, _, _ in attached} == {"HK-HKD-STANDARD", "HK-HKD-PREMIUM"}
    assert all(status == "draft" for _, _, status in attached)
    assert len([a for a in attached if a[0] == "HK-HKD-PREMIUM"]) == 7
    unattached = set(db.scalars(select(BenefitDefinition.code))) - {b for _, b, _ in attached}
    assert all(c.startswith(("GEN-", "IE-")) for c in unattached) and len(unattached) == 14


# ------------------------------------------------------------------------------- database guards


def _db_error(session: Session, sql: str, fragment: str, params: dict[str, Any] | None = None) -> None:
    with pytest.raises(DBAPIError) as info, session.begin_nested():
        session.execute(text(sql), params or {})
    assert fragment in str(info.value), str(info.value)


def _version_id(session: Session, code: str, no: int = 1) -> uuid.UUID:
    found = session.scalar(
        select(PriceBookVersion.id)
        .join(PriceBook, PriceBook.id == PriceBookVersion.price_book_id)
        .where(PriceBook.code == code, PriceBookVersion.version_no == no)
    )
    assert found is not None
    return found


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE price_book_entries SET package_total_minor = package_total_minor + 1",
        "DELETE FROM price_book_entries",
    ],
)
def test_supplied_figures_cannot_be_changed_by_the_application(db: Session, sql: str) -> None:
    _db_error(db, sql, "permission denied")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE price_book_entries SET package_total_minor = package_total_minor + 1",
        "DELETE FROM price_book_entries",
        "TRUNCATE price_book_entries CASCADE",
    ],
)
def test_supplied_figures_cannot_be_changed_even_by_the_owner(owner_db: Session, sql: str) -> None:
    _db_error(owner_db, sql, "append-only")


def test_no_entries_can_be_added_to_a_locked_version(owner_db: Session) -> None:
    _db_error(
        owner_db,
        "INSERT INTO price_book_entries (id, price_book_version_id, package_code, display_name, quantity, "
        "package_total_minor) VALUES (gen_random_uuid(), :v, '25H', '25h', 25, 1)",
        "is locked",
        {"v": _version_id(owner_db, "UK-GBP-TIER-A")},
    )


def test_version_and_book_guards(owner_db: Session) -> None:
    v = {"v": _version_id(owner_db, "MY-MYR")}
    _db_error(owner_db, "DELETE FROM price_book_versions WHERE id = :v", "never deleted", v)
    _db_error(owner_db, "UPDATE price_book_versions SET figures_locked = false WHERE id = :v", "cannot be unlocked", v)
    _db_error(owner_db, "UPDATE price_book_versions SET source_document = 'x' WHERE id = :v", "never change", v)
    _db_error(owner_db, "UPDATE price_book_versions SET status = 'active' WHERE id = :v", "active_requirements", v)
    _db_error(owner_db, "UPDATE price_books SET currency_code = 'USD' WHERE code = 'MY-MYR'", "never change")
    _db_error(owner_db, "DELETE FROM price_books WHERE code = 'MY-MYR'", "never deleted")
    owner_db.execute(text("UPDATE price_book_versions SET status = 'rejected' WHERE id = :v"), v)
    _db_error(owner_db, "UPDATE price_book_versions SET status = 'draft' WHERE id = :v", "is closed", v)


# ------------------------------------------------------------------------------- helpers


@pytest.fixture
def managers(db: Session) -> tuple[TestUser, TestUser]:
    return make_user(db, [("pricing_manager", None)]), make_user(db, [("pricing_manager", None)])


def _ctx(db: Session, user: TestUser) -> tuple[Actor, Any]:
    return user.actor, load_access(db, user.actor)


def _ready(db: Session, code: str, first: TestUser, second: TestUser, *, skip: str | None = None) -> uuid.UUID:
    """Take a supplied version through every activation requirement except ``skip``; returns its id."""
    version_id = _version_id(db, code)
    a1, acc1 = _ctx(db, first)
    a2, acc2 = _ctx(db, second)
    if skip != "G-01":
        pricing.confirm_figures(db, a1, acc1, version_id, "BD-901", "Figures checked with Mixt (test)")
    if skip != "G-05":
        pricing.set_tax_treatment(db, a1, acc1, version_id, "inclusive", "BD-902")
    if skip != "G-06":
        for benefit_id in db.scalars(
            select(PackageBenefit.id).where(PackageBenefit.price_book_version_id == version_id)
        ):
            pricing.approve_benefit(db, a1, acc1, benefit_id)
    book_id = db.scalar(select(PriceBookVersion.price_book_id).where(PriceBookVersion.id == version_id))
    if skip != "G-03":
        for assignment in db.scalars(
            select(PriceBookMarketAssignment).where(
                PriceBookMarketAssignment.price_book_id == book_id,
                PriceBookMarketAssignment.requires_relationship_confirmation,
                PriceBookMarketAssignment.relationship_confirmed_ref.is_(None),
            )
        ):
            pricing.confirm_relationship(db, a1, acc1, assignment.id, "BD-903")
    pricing.submit(db, a1, acc1, version_id)
    if skip != "G-07":
        pricing.approve(db, a2, acc2, version_id)
        owner = make_user(db, [("owner", None)])
        pricing.approve(db, owner.actor, load_access(db, owner.actor), version_id)
    return version_id


def _live(db: Session, code: str, first: TestUser, second: TestUser) -> uuid.UUID:
    version_id = _ready(db, code, first, second)
    actor, access = _ctx(db, first)
    pricing.activate(db, actor, access, version_id)
    return version_id


def _gate(db: Session, version_id: uuid.UUID, user: TestUser) -> dict[str, pricing.GateCheck]:
    _actor, access = _ctx(db, user)
    return {c.code: c for c in pricing.view_version(db, access, version_id).gate}


# ------------------------------------------------------------------------------- activation gate


def test_gate_shows_why_each_supplied_book_is_not_live(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    user = managers[0]
    uk = _gate(db, _version_id(db, "UK-GBP-TIER-A"), user)
    assert [c for c, check in uk.items() if not check.ok] == ["G-01", "G-05", "G-07"]
    assert "Q-PAY-04" in uk["G-05"].questions and "manual" in uk["G-03"].detail
    usd = _gate(db, _version_id(db, "USD-SCHEDULE-A"), user)
    assert not usd["G-02"].ok and "Q-MKT-01" in usd["G-02"].questions
    ireland = _gate(db, _version_id(db, "IE-EUR-SCHEDULE-B"), user)
    assert not ireland["G-03"].ok and "Q-PRC-03" in ireland["G-03"].questions
    hk = _gate(db, _version_id(db, "HK-HKD-PREMIUM"), user)
    assert not hk["G-06"].ok and "7 not approved" in hk["G-06"].detail
    qatar = _gate(db, _version_id(db, "QA-QAR"), user)
    assert qatar["G-03"].ok and qatar["G-04"].ok and qatar["G-06"].ok


@pytest.mark.parametrize("skip", ["G-01", "G-03", "G-05", "G-06"])
def test_each_missing_requirement_blocks_activation(
    db: Session, managers: tuple[TestUser, TestUser], skip: str
) -> None:
    code = {"G-03": "IE-EUR-SCHEDULE-A", "G-06": "HK-HKD-STANDARD"}.get(skip, "UK-GBP-TIER-B")
    version_id = _ready(db, code, *managers, skip=skip)
    actor, access = _ctx(db, managers[0])
    with pytest.raises(Conflict) as info:
        pricing.activate(db, actor, access, version_id)
    assert info.value.code == "ACTIVATION_GATE_FAILED"
    assert [m.split(" ")[0] for m in info.value.extra["missing"]] == [skip]


def test_unapproved_version_cannot_be_activated(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    version_id = _ready(db, "QA-QAR", *managers, skip="G-07")
    actor, access = _ctx(db, managers[0])
    with pytest.raises(Conflict) as info:
        pricing.activate(db, actor, access, version_id)
    assert info.value.code == "INVALID_TRANSITION"


def test_usd_book_needs_a_market_decision(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    version_id = _ready(db, "USD-SCHEDULE-A", *managers)
    actor, access = _ctx(db, managers[0])
    with pytest.raises(Conflict) as info:
        pricing.activate(db, actor, access, version_id)
    assert [m.split(" ")[0] for m in info.value.extra["missing"]] == ["G-02"]
    book = db.scalar(select(PriceBook).where(PriceBook.code == "USD-SCHEDULE-A"))
    assert book is not None
    with pytest.raises(ValidationFailed) as no_ref:
        pricing.assign_market(db, actor, access, book.id, market_id(db, "SG"), "", "")
    assert no_ref.value.code == "DECISION_REF_REQUIRED"
    pricing.assign_market(db, actor, access, book.id, market_id(db, "SG"), "BD-904", "test decision")
    assert pricing.activate(db, actor, access, version_id).version.status == "active"


# ------------------------------------------------------------------------------- lifecycle


def test_approval_needs_different_people(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    first, second = managers
    version_id = _version_id(db, "SA-SAR")
    a1, acc1 = _ctx(db, first)
    a2, acc2 = _ctx(db, second)
    pricing.submit(db, a1, acc1, version_id)
    with pytest.raises(PermissionDenied) as own:
        pricing.approve(db, a1, acc1, version_id)
    assert own.value.code == "FOUR_EYES"
    view = pricing.approve(db, a2, acc2, version_id)
    assert view.version.status == "in_review"  # dual approval is on by default
    with pytest.raises(Conflict) as twice:
        pricing.approve(db, a2, acc2, version_id)
    assert twice.value.code == "SECOND_APPROVER_REQUIRED"
    third = make_user(db, [("pricing_manager", None)])
    approved = pricing.approve(db, third.actor, load_access(db, third.actor), version_id)
    assert approved.version.status == "approved" and approved.version.content_hash


def test_single_approval_when_dual_approval_is_off(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    owner = make_user(db, [("owner", None)])
    settings_service.change(
        db, owner.actor, load_access(db, owner.actor), "pricing.activation.dual_approval", False, "confirmed", "BD-905"
    )
    first, second = managers
    version_id = _version_id(db, "SA-SAR")
    pricing.submit(db, first.actor, load_access(db, first.actor), version_id)
    assert pricing.approve(db, second.actor, load_access(db, second.actor), version_id).version.status == "approved"


def test_confirmations_need_a_decision_reference(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    actor, access = _ctx(db, managers[0])
    version_id = _version_id(db, "QA-QAR")
    for call in (
        lambda: pricing.confirm_figures(db, actor, access, version_id, "yes", "checked"),
        lambda: pricing.set_tax_treatment(db, actor, access, version_id, "inclusive", "BD-1"),
    ):
        with pytest.raises(ValidationFailed) as info:
            call()
        assert info.value.code == "DECISION_REF_REQUIRED"


def test_sales_staff_cannot_change_pricing(db: Session) -> None:
    rep = make_user(db, [("sales_manager", None)])
    with pytest.raises(PermissionDenied):
        pricing.submit(db, rep.actor, load_access(db, rep.actor), _version_id(db, "QA-QAR"))


def test_activation_supersedes_and_history_is_kept(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    v1 = _live(db, "QA-QAR", *managers)
    actor, access = _ctx(db, managers[0])
    original = [(e.package_code, e.package_total_minor) for e in pricing.entries_of(db, v1)]
    corrected = [
        pricing.NewEntry(f"{q}H", f"{q}h", Decimal(q), t)
        for q, t in [(15, 105000), (20, 130000), (30, 180000), (40, 228000), (60, 318000), (100, 490000)]
    ]
    view, _notes = pricing.create_correction(
        db, actor, access, v1, corrected, "Corrected Qatar sheet (test)", date(2026, 11, 10), "Test correction loaded"
    )
    v2 = view.version.id
    assert view.version.change_type == "correction" and view.version.supersedes_version_id == v1
    assert db.get(PriceBookVersion, v1).status == "active"  # type: ignore[union-attr]  # until v2 goes live
    _ready_existing(db, v2, *managers)
    pricing.activate(db, actor, access, v2)
    old = db.get(PriceBookVersion, v1)
    assert old is not None and old.status == "superseded" and old.effective_to is not None
    assert [(e.package_code, e.package_total_minor) for e in pricing.entries_of(db, v1)] == original


def _ready_existing(db: Session, version_id: uuid.UUID, first: TestUser, second: TestUser) -> None:
    a1, acc1 = _ctx(db, first)
    pricing.confirm_figures(db, a1, acc1, version_id, "BD-906", "Corrected figures confirmed (test)")
    pricing.set_tax_treatment(db, a1, acc1, version_id, "inclusive", "BD-902")
    pricing.submit(db, a1, acc1, version_id)
    pricing.approve(db, second.actor, load_access(db, second.actor), version_id)
    owner = make_user(db, [("owner", None)])
    pricing.approve(db, owner.actor, load_access(db, owner.actor), version_id)


def test_malaysia_correction_keeps_version_1(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    actor, access = _ctx(db, managers[0])
    v1 = _version_id(db, "MY-MYR")
    before = [(e.package_code, e.package_total_minor) for e in pricing.entries_of(db, v1)]
    corrected = [
        pricing.NewEntry("15H", "15h", Decimal(15), 117000),
        pricing.NewEntry("20H", "20h", Decimal(20), 160000),  # rate goes up from 15h: flagged, not changed
        pricing.NewEntry("30H", "30h", Decimal(30), 210001),  # not a whole rate: flagged
    ]
    view, notes = pricing.create_correction(
        db,
        actor,
        access,
        v1,
        corrected,
        "Malaysia corrected sheet (test)",
        date(2026, 11, 10),
        "Q-PRC-21 answer (test)",
    )
    assert view.version.version_no == 2 and view.version.figures_locked
    assert any("20h: the effective rate goes up" in n for n in notes)
    assert any("30h: the effective rate" in n and "whole number" in n for n in notes)
    original = db.get(PriceBookVersion, v1)
    assert original is not None and original.status == "rejected" and "version 2" in (original.status_reason or "")
    assert [(e.package_code, e.package_total_minor) for e in pricing.entries_of(db, v1)] == before
    with pytest.raises(Conflict) as closed:
        pricing.create_correction(db, actor, access, v1, corrected, "x sheet", date(2026, 11, 10), "again, on v1")
    assert closed.value.code == "VERSION_CLOSED"


def test_identical_figures_are_pointed_out(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    actor, access = _ctx(db, managers[0])
    same_as_uae_b = [
        pricing.NewEntry(f"{q}H", f"{q}h", Decimal(q), t)
        for q, t in [(15, 112500), (20, 140000), (30, 195000), (40, 240000)]
    ]
    _view, notes = pricing.create_correction(
        db, actor, access, _version_id(db, "QA-QAR"), same_as_uae_b, "sheet", date(2026, 11, 10), "test of DC-04"
    )
    assert any("identical to AE-AED-TIER-B" in n for n in notes)


def test_return_reject_retire(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    actor, access = _ctx(db, managers[0])
    version_id = _ready(db, "QA-QAR", *managers)
    assert pricing.return_to_draft(db, actor, access, version_id, "needs another look").version.content_hash is None
    pricing.submit(db, actor, access, version_id)
    assert pricing.reject(db, actor, access, version_id, "wrong sheet").version.status == "rejected"
    live = _live(db, "SA-SAR", *managers)
    assert pricing.retire(db, actor, access, live, "stopped selling").version.status == "retired"


# ------------------------------------------------------------------------------- customers and resolution


def _customer(db: Session, country: str | None, owner: TestUser | None = None) -> uuid.UUID:
    """An account; when ``country`` is given, its market is confirmed by a person."""
    owner = owner or make_user(db, [("sales_manager", None)])
    actor, access = owner.actor, load_access(db, owner.actor)
    account = crm.create_account(db, actor, access, "Test household")
    if country:
        crm.confirm_market(
            db, actor, access, account.id, market_id(db, country), "Parent confirmed (test)", account.version
        )
    return account.id


def _refusal(db: Session, account_id: uuid.UUID, **kw: Any) -> resolution.PricingUnavailable:
    with pytest.raises(resolution.PricingUnavailable) as info:
        resolution.resolve_options(db, account_id, **kw)
    return info.value


def test_nothing_can_be_quoted_today(db: Session) -> None:
    for country in ("GB", "AE", "SA", "QA", "MY", "IE", "HK"):
        refusal = _refusal(db, _customer(db, country))
        assert refusal.code == "NO_APPROVED_PRICING_FOR_MARKET"
        assert refusal.extra["escalation_required"] is True
        assert "team will confirm" in refusal.extra["customer_safe_message"]


def test_market_is_never_inferred_for_pricing(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    for code in ("USD-SCHEDULE-A", "UK-GBP-TIER-A"):
        _ready(db, code, *managers)
    actor, access = _ctx(db, managers[0])
    usd = db.scalar(select(PriceBook).where(PriceBook.code == "USD-SCHEDULE-A"))
    assert usd is not None
    pricing.assign_market(db, actor, access, usd.id, market_id(db, "SG"), "BD-904", "test")
    pricing.activate(db, actor, access, _version_id(db, "USD-SCHEDULE-A"))
    account = _customer(db, None)  # USD budget, +1 phone, American curriculum: none of these sets a market
    assert _refusal(db, account).code == "MARKET_NOT_CONFIRMED"


def test_unpriced_markets_never_borrow_other_pricing(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    for country in ("KW", "OM", "BH", "SG", "ID", "KR"):
        assert _refusal(db, _customer(db, country)).code == "NO_APPROVED_PRICING_FOR_MARKET"


def test_single_book_market(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    _live(db, "QA-QAR", *managers)
    account = _customer(db, "QA")
    first = resolution.resolve_options(db, account)
    again = resolution.resolve_options(db, account, at=first.at)
    assert first == again  # deterministic
    assert [o.package_total_minor for o in first.options] == [
        105000,
        130000,
        180000,
        228000,
        318000,
        490000,
        660000,
        760000,
    ]
    option = first.options[2]
    assert option.currency == "QAR" and option.package_total_display == "QAR 1,800"
    assert option.derived_unit_rate_display == "QAR 60 per hour (derived)"
    assert option.tier_selection_id is None and option.benefits == ()
    assert _refusal(db, account, quantity=Decimal(25)).extra["nearest_options"] == ["QA-QAR 20h", "QA-QAR 30h"]
    assert _refusal(db, account, plan_type="premium").code == "PLAN_NOT_OFFERED_IN_MARKET"
    exact = resolution.resolve_options(db, account, quantity=Decimal(30))
    assert [o.display_name for o in exact.options] == ["30h"]
    assert _refusal(db, account, at=now_utc() - timedelta(days=1)).code == "NO_APPROVED_PRICING_FOR_MARKET"


def test_tiers_are_chosen_by_a_person(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    _live(db, "UK-GBP-TIER-A", *managers)
    _live(db, "UK-GBP-TIER-B", *managers)
    seller = make_user(db, [("sales_manager", None)])
    account = _customer(db, "GB", seller)
    refusal = _refusal(db, account)
    assert refusal.code == "TIER_DECISION_REQUIRED"
    assert refusal.extra["choices"] == ["UK-GBP-TIER-A", "UK-GBP-TIER-B"]
    assert "tier" not in refusal.extra["customer_safe_message"].lower()  # never mention tiers to customers
    tier_b = db.scalar(select(PriceBook).where(PriceBook.code == "UK-GBP-TIER-B"))
    assert tier_b is not None
    agent = Actor(principal_id=seller.user.principal_id, kind="agent")
    with pytest.raises(PermissionDenied) as robot:
        pricing.select_tier(db, agent, load_access(db, seller.actor), account, tier_b.id, "AI thinks so")
    assert robot.value.code == "PERSON_REQUIRED"
    pricing.select_tier(db, seller.actor, load_access(db, seller.actor), account, tier_b.id, "Agreed with parent")
    found = resolution.resolve_options(db, account, quantity=Decimal(30))
    assert [(o.price_book_code, o.package_total_display) for o in found.options] == [("UK-GBP-TIER-B", "GBP 570")]
    assert found.options[0].tier_selection_id is not None


def test_a_tier_is_never_chosen_because_only_one_is_live(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    _live(db, "AE-AED-TIER-A", *managers)
    seller = make_user(db, [("sales_manager", None)])
    account = _customer(db, "AE", seller)
    assert _refusal(db, account).code == "TIER_DECISION_REQUIRED"
    tier_b = db.scalar(select(PriceBook).where(PriceBook.code == "AE-AED-TIER-B"))
    assert tier_b is not None
    pricing.select_tier(db, seller.actor, load_access(db, seller.actor), account, tier_b.id, "Agreed with parent")
    assert _refusal(db, account).code == "NO_APPROVED_PRICING_FOR_MARKET"  # never falls back to Tier A


def test_tier_selection_rules(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    seller = make_user(db, [("sales_manager", None)])
    actor, access = seller.actor, load_access(db, seller.actor)
    qatar = db.scalar(select(PriceBook).where(PriceBook.code == "QA-QAR"))
    uk_a = db.scalar(select(PriceBook).where(PriceBook.code == "UK-GBP-TIER-A"))
    assert qatar is not None and uk_a is not None
    with pytest.raises(ValidationFailed) as unconfirmed:
        pricing.select_tier(db, actor, access, _customer(db, None, seller), uk_a.id, "reason given")
    assert unconfirmed.value.code == "MARKET_NOT_CONFIRMED"
    with pytest.raises(ValidationFailed) as not_choice:
        pricing.select_tier(db, actor, access, _customer(db, "QA", seller), qatar.id, "reason given")
    assert not_choice.value.code == "NOT_A_TIER_CHOICE"
    with pytest.raises(ValidationFailed) as other_market:
        pricing.select_tier(db, actor, access, _customer(db, "AE", seller), uk_a.id, "reason given")
    assert other_market.value.code == "NOT_A_TIER_CHOICE"
    account = _customer(db, "GB", seller)
    first = pricing.select_tier(db, actor, access, account, uk_a.id, "First choice")
    uk_b = db.scalar(select(PriceBook).where(PriceBook.code == "UK-GBP-TIER-B"))
    assert uk_b is not None
    second = pricing.select_tier(db, actor, access, account, uk_b.id, "Changed after call")
    history = pricing.list_tier_selections(db, access, account)
    assert [(h.book_code, h.selection.status) for h in history] == [
        ("UK-GBP-TIER-B", "active"),
        ("UK-GBP-TIER-A", "replaced"),
    ]
    assert history[1].selection.replaced_by_id == second.selection.id and first.selection.id == history[1].selection.id
    revoked = pricing.revoke_tier_selection(db, actor, access, second.selection.id, "Customer withdrew")
    assert revoked.selection.status == "revoked"


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(quantity=st.integers(min_value=1, max_value=250))
def test_quantities_are_never_interpolated(db: Session, managers: tuple[TestUser, TestUser], quantity: int) -> None:
    if db.scalar(select(PriceBookVersion.id).where(PriceBookVersion.status == "active")) is None:
        _live(db, "SA-SAR", *managers)
    account = db.info.get("sa_account") or _customer(db, "SA")
    db.info["sa_account"] = account
    listed = {15, 20, 30, 40, 60, 100, 150, 200}
    if quantity in listed:
        found = resolution.resolve_options(db, account, quantity=Decimal(quantity))
        assert [int(o.quantity) for o in found.options] == [quantity]
    else:
        assert _refusal(db, account, quantity=Decimal(quantity)).code == "QUANTITY_NOT_OFFERED"


def test_every_market_only_ever_sees_its_own_books(db: Session, managers: tuple[TestUser, TestUser]) -> None:
    """With every supplied book live, no customer ever gets another market's or another currency's entries."""
    actor, access = _ctx(db, managers[0])
    usd_a = db.scalar(select(PriceBook).where(PriceBook.code == "USD-SCHEDULE-A"))
    assert usd_a is not None
    pricing.assign_market(db, actor, access, usd_a.id, market_id(db, "SG"), "BD-904", "test")
    for code in [c for (c,) in db.execute(select(PriceBook.code).order_by(PriceBook.code))]:
        if code != "USD-SCHEDULE-B":
            _live(db, code, *managers)
    seller = make_user(db, [("sales_manager", None)])
    expected = {
        "GB": {"GBP"},
        "AE": {"AED"},
        "SA": {"SAR"},
        "QA": {"QAR"},
        "MY": {"MYR"},
        "IE": {"EUR"},
        "HK": {"HKD"},
        "SG": {"USD"},
    }
    for country, currencies in expected.items():
        account = _customer(db, country, seller)
        for plan, books in pricing.tier_choices(db, market_id(db, country)).items():
            pricing.select_tier(db, seller.actor, load_access(db, seller.actor), account, books[-1].id, "Chosen")
            assert plan in ("standard", "premium")
        found = resolution.resolve_options(db, account)
        assert {o.currency for o in found.options} == currencies, country
        assert found.market_country == country
        for option in found.options:
            assigned = db.scalar(
                select(PriceBookMarketAssignment.assignment_status).where(
                    PriceBookMarketAssignment.price_book_id == option.price_book_id,
                    PriceBookMarketAssignment.market_id == market_id(db, country),
                )
            )
            assert assigned == "confirmed"
    hk = resolution.resolve_options(db, _customer(db, "HK", seller))
    assert {o.plan_type for o in hk.options} == {"standard", "premium"}  # separate plans, both offered
    assert any(o.benefits for o in hk.options)  # approved benefits travel with the option


# ------------------------------------------------------------------------------- API


def test_pricing_api_for_managers_and_sales(as_user: Any, db: Session) -> None:
    manager, _ = as_user([("pricing_manager", None)])
    books = manager.get("/api/v1/pricing/books")
    assert books.status_code == 200 and len(books.json()) == 13
    uk = next(b for b in books.json() if b["code"] == "UK-GBP-TIER-A")
    assert uk["active_version_no"] is None and uk["latest_version"]["status"] == "draft"
    version = manager.get(f"/api/v1/pricing/versions/{uk['latest_version']['id']}").json()
    assert version["entries"][0]["package_total_display"] == "GBP 285"
    assert version["entries"][0]["derived_unit_rate_display"] == "GBP 19 per hour (derived)"
    assert version["gate_passes"] is False and len(version["gate"]) == 9
    status = manager.get("/api/v1/pricing/status").json()
    assert status["catalogue_complete"] is False and status["active_versions"] == 0
    kuwait = next(m for m in status["markets"] if m["country_code"] == "KW")
    assert kuwait["books"] == []
    gb = next(m for m in status["markets"] if m["country_code"] == "GB")
    assert gb["books"] == ["UK-GBP-TIER-A", "UK-GBP-TIER-B"] and gb["active_books"] == []
    definitions = manager.get("/api/v1/pricing/benefit-definitions").json()
    assert len(definitions) == 25

    correction = manager.post(
        f"/api/v1/pricing/versions/{_version_id(db, 'MY-MYR')}/corrections",
        json={
            "source_document": "Malaysia corrected sheet (test)",
            "source_received_on": "2026-11-10",
            "change_summary": "Corrected totals supplied by Mixt (test)",
            "entries": [{"package_code": "15H", "display_name": "15h", "quantity": "15", "package_total": "1170.505"}],
        },
    )
    assert correction.status_code == 422 and correction.json()["code"] == "INVALID_AMOUNT"

    rep, _ = as_user([("sales_rep", None)])
    assert rep.get("/api/v1/pricing/books").status_code == 403
    account = rep.post(ACCOUNTS, json={"display_name": "API household"}).json()
    refused = rep.get(f"/api/v1/accounts/{account['id']}/pricing/options")
    assert refused.status_code == 409
    body = refused.json()
    assert body["code"] == "MARKET_NOT_CONFIRMED" and body["escalation_required"] is True
    tiers = rep.get(f"/api/v1/accounts/{account['id']}/pricing/tiers").json()
    assert tiers == {"market_confirmed": False, "choices": [], "history": []}

    seller, seller_user = as_user([("sales_manager", None)])
    household = seller.post(ACCOUNTS, json={"display_name": "UK household"}).json()
    seller.post(
        f"{ACCOUNTS}/{household['id']}/market-confirmation",
        json={"market_id": str(market_id(db, "GB")), "note": "Parent lives in London"},
        headers={"If-Match": f'"{household["version"]}"'},
    )
    choices = seller.get(f"/api/v1/accounts/{household['id']}/pricing/tiers").json()
    assert [b["code"] for b in choices["choices"][0]["books"]] == ["UK-GBP-TIER-A", "UK-GBP-TIER-B"]
    tier_a = choices["choices"][0]["books"][0]["price_book_id"]
    chosen = seller.post(
        f"/api/v1/accounts/{household['id']}/pricing/tiers", json={"price_book_id": tier_a, "reason": "Agreed by phone"}
    )
    assert chosen.status_code == 201 and chosen.json()["selected_by_user_id"] == str(seller_user.id)
    again = seller.get(f"/api/v1/accounts/{household['id']}/pricing/tiers").json()
    assert again["choices"][0]["current"]["price_book_code"] == "UK-GBP-TIER-A"
    other_rep, _ = as_user([("sales_rep", None)])
    assert other_rep.get(f"/api/v1/accounts/{household['id']}/pricing/options").status_code == 404
