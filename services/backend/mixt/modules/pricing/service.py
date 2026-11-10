"""Pricing catalogue, version lifecycle, activation gate, corrections and tier selection (docs/04).

Rules this module enforces (with the database as a second line, migration 0004):
* figures are never edited: a correction is a new version, the original is kept (ADR-14);
* nothing goes live unless every activation check passes (docs/04 §5.2, G-01 to G-09);
* Mixt's confirmations (figures, tax treatment, market assignment, Ireland schedule relationship)
  are recorded only with a decision-log reference: the system never assumes them;
* approval needs a different person from the one who submitted, and two different approvers while
  ``pricing.activation.dual_approval`` is on;
* a tier/schedule is selected for a customer only by a person, with a reason (ADR-12).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.identity.access import Access
from mixt.modules.pipeline import service as pipeline
from mixt.modules.pricing.models import (
    TAX_TREATMENTS,
    BenefitDefinition,
    PackageBenefit,
    PriceBook,
    PriceBookEntry,
    PriceBookMarketAssignment,
    PriceBookVersion,
    PricingTierSelection,
)
from mixt.modules.reference import service as reference
from mixt.modules.settings import service as settings

# Public names for the API layer (the ORM classes stay private to this module).
Version = PriceBookVersion
Assignment = PriceBookMarketAssignment

DECISION_REF = re.compile(r"^BD-[0-9]{3}$")
CLOSED = frozenset({"superseded", "retired", "rejected"})
EDITABLE_CONFIRMATIONS = frozenset({"draft", "in_review"})


def _decision_ref(value: str | None, what: str) -> str:
    if not value or not DECISION_REF.match(value.strip()):
        raise ValidationFailed(
            "DECISION_REF_REQUIRED",
            f"{what} is Mixt's decision: record it in the decision log first and give its reference, e.g. 'BD-034'.",
        )
    return value.strip()


# ------------------------------------------------------------------------------------- reading


@dataclass(frozen=True)
class GateCheck:
    code: str
    title: str
    ok: bool
    detail: str
    questions: tuple[str, ...] = ()


@dataclass
class VersionView:
    version: PriceBookVersion
    book: PriceBook
    entries: list[PriceBookEntry]
    benefits: list[tuple[PackageBenefit, BenefitDefinition]]
    gate: list[GateCheck] = field(default_factory=list)

    @property
    def gate_passes(self) -> bool:
        return all(check.ok for check in self.gate)


@dataclass
class BookView:
    book: PriceBook
    versions: list[PriceBookVersion]
    assignments: list[tuple[PriceBookMarketAssignment, str, str]]  # (assignment, market name, country)

    @property
    def active_version(self) -> PriceBookVersion | None:
        return next((v for v in self.versions if v.status == "active"), None)

    @property
    def latest_version(self) -> PriceBookVersion:
        return max(self.versions, key=lambda v: v.version_no)


def _assignments(db: Session, book_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[tuple[Any, str, str]]]:
    result: dict[uuid.UUID, list[tuple[Any, str, str]]] = {b: [] for b in book_ids}
    rows = db.scalars(
        select(PriceBookMarketAssignment)
        .where(PriceBookMarketAssignment.price_book_id.in_(book_ids))
        .order_by(PriceBookMarketAssignment.created_at)
    )
    for row in rows:
        market = reference.require_market(db, row.market_id)
        result[row.price_book_id].append((row, market.name, market.country_code))
    return result


def list_books(db: Session, access: Access) -> list[BookView]:
    access.require_somewhere("pricing.read")
    books = list(db.scalars(select(PriceBook).order_by(PriceBook.code)))
    ids = [b.id for b in books]
    versions: dict[uuid.UUID, list[PriceBookVersion]] = {b: [] for b in ids}
    for version in db.scalars(
        select(PriceBookVersion).where(PriceBookVersion.price_book_id.in_(ids)).order_by(PriceBookVersion.version_no)
    ):
        versions[version.price_book_id].append(version)
    assignments = _assignments(db, ids)
    return [BookView(b, versions[b.id], assignments[b.id]) for b in books]


def get_book(db: Session, access: Access, book_id: uuid.UUID) -> BookView:
    access.require_somewhere("pricing.read")
    book = db.get(PriceBook, book_id)
    if book is None:
        raise NotFound("PRICE_BOOK_NOT_FOUND", "Price book not found.")
    versions = list(
        db.scalars(
            select(PriceBookVersion)
            .where(PriceBookVersion.price_book_id == book.id)
            .order_by(PriceBookVersion.version_no)
        )
    )
    return BookView(book, versions, _assignments(db, [book.id])[book.id])


def _version(db: Session, version_id: uuid.UUID, *, lock: bool = False) -> PriceBookVersion:
    query = select(PriceBookVersion).where(PriceBookVersion.id == version_id)
    version = db.scalar(query.with_for_update() if lock else query)
    if version is None:
        raise NotFound("PRICE_BOOK_VERSION_NOT_FOUND", "Price book version not found.")
    return version


def entries_of(db: Session, version_id: uuid.UUID) -> list[PriceBookEntry]:
    return list(
        db.scalars(
            select(PriceBookEntry)
            .where(PriceBookEntry.price_book_version_id == version_id)
            .order_by(PriceBookEntry.quantity)
        )
    )


def _benefits(db: Session, version_id: uuid.UUID) -> list[tuple[PackageBenefit, BenefitDefinition]]:
    rows = db.execute(
        select(PackageBenefit, BenefitDefinition)
        .join(BenefitDefinition, BenefitDefinition.id == PackageBenefit.benefit_definition_id)
        .where(PackageBenefit.price_book_version_id == version_id)
        .order_by(PackageBenefit.sort_order)
    )
    return [(b, d) for b, d in rows.tuples()]


def view_version(db: Session, access: Access, version_id: uuid.UUID) -> VersionView:
    access.require_somewhere("pricing.read")
    version = _version(db, version_id)
    return _view(db, version)


def _view(db: Session, version: PriceBookVersion) -> VersionView:
    book = db.get(PriceBook, version.price_book_id)
    assert book is not None  # noqa: S101 (foreign key)
    view = VersionView(version, book, entries_of(db, version.id), _benefits(db, version.id))
    view.gate = gate_report(db, version, book, view.entries, view.benefits)
    return view


def benefit_definitions(db: Session, access: Access) -> list[tuple[BenefitDefinition, int]]:
    """All supplied benefit definitions, with how many versions they are attached to."""
    access.require_somewhere("pricing.read")
    rows = db.execute(
        select(PackageBenefit.benefit_definition_id, func.count()).group_by(PackageBenefit.benefit_definition_id)
    )
    counts = {row[0]: int(row[1]) for row in rows}
    definitions = db.scalars(select(BenefitDefinition).order_by(BenefitDefinition.code))
    return [(d, int(counts.get(d.id, 0))) for d in definitions]


# ------------------------------------------------------------------------------ content hash


def content_hash(book: PriceBook, version: PriceBookVersion, entries: list[PriceBookEntry]) -> str:
    """SHA-256 of everything a customer would be charged by: book identity, unit and every entry."""
    canonical = {
        "book": book.code,
        "currency": book.currency_code,
        "unit_type": book.unit_type,
        "minutes_per_unit": version.session_minutes_per_unit,
        "version_no": version.version_no,
        "entries": [
            [e.package_code, str(Decimal(e.quantity).normalize()), e.package_total_minor, e.advertised_unit_rate_minor]
            for e in sorted(entries, key=lambda x: Decimal(x.quantity))
        ],
    }
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------- activation gate


def _competing_books(db: Session, market_id: uuid.UUID, plan_type: str) -> list[PriceBook]:
    """Public books of one plan type with a confirmed assignment to the market."""
    return list(
        db.scalars(
            select(PriceBook)
            .join(PriceBookMarketAssignment, PriceBookMarketAssignment.price_book_id == PriceBook.id)
            .where(
                PriceBookMarketAssignment.market_id == market_id,
                PriceBookMarketAssignment.assignment_status == "confirmed",
                PriceBook.plan_type == plan_type,
                PriceBook.audience == "public",
                PriceBook.archived_at.is_(None),
            )
            .order_by(PriceBook.code)
        )
    )


def gate_report(
    db: Session,
    version: PriceBookVersion,
    book: PriceBook,
    entries: list[PriceBookEntry],
    benefits: list[tuple[PackageBenefit, BenefitDefinition]],
) -> list[GateCheck]:
    checks: list[GateCheck] = []
    # G-01 figures confirmed by Mixt and the data review signed off
    confirmed = version.figures_confirmation == "confirmed" and version.figures_locked
    checks.append(
        GateCheck(
            "G-01",
            "Figures confirmed by Mixt and data review signed off",
            confirmed,
            f"confirmed ({version.figures_confirmation_ref})" if confirmed else "supplied, not yet confirmed by Mixt",
            () if confirmed else ("Q-PRC-14", "Q-PRC-15", "Q-PRC-16", "Q-PRC-17", "Q-PRC-21"),
        )
    )
    # G-02 at least one confirmed market assignment to an active market
    assignments = list(
        db.scalars(
            select(PriceBookMarketAssignment).where(
                PriceBookMarketAssignment.price_book_id == book.id,
                PriceBookMarketAssignment.assignment_status == "confirmed",
            )
        )
    )
    active_markets = [a for a in assignments if reference.require_market(db, a.market_id).status == "active"]
    checks.append(
        GateCheck(
            "G-02",
            "Confirmed market assignment",
            bool(active_markets),
            ", ".join(f"{reference.require_market(db, a.market_id).name} ({a.decision_ref})" for a in active_markets)
            or "no confirmed market: this book cannot be offered anywhere",
            () if active_markets else ("Q-MKT-01",),
        )
    )
    # G-03 several valid books in a market: selection mode set; Ireland: relationship confirmed
    g03_ok, g03_detail = True, "only book of its plan type in its market(s)"
    g03_questions: tuple[str, ...] = ()
    for assignment in active_markets:
        competitors = _competing_books(db, assignment.market_id, book.plan_type)
        market = reference.require_market(db, assignment.market_id)
        if len(competitors) > 1:
            mode = settings.get_value(db, "pricing.tier_selection_mode", "market", str(assignment.market_id))
            names = ", ".join(c.code for c in competitors)
            g03_detail = f"{market.name}: {len(competitors)} valid books ({names}); selection mode '{mode}'"
            if mode == "market_default" and not any(
                a.is_market_default
                for a in db.scalars(
                    select(PriceBookMarketAssignment).where(PriceBookMarketAssignment.market_id == assignment.market_id)
                )
            ):
                g03_ok, g03_detail = False, g03_detail + ": no market default set"
                g03_questions = ("Q-PRC-02",)
            if mode == "rule_based":
                g03_ok, g03_detail = False, g03_detail + ": no approved eligibility rule exists"
                g03_questions = ("Q-PRC-02",)
        if assignment.requires_relationship_confirmation and not assignment.relationship_confirmed_ref:
            g03_ok = False
            g03_detail = f"{market.name}: the relationship between its schedules is not confirmed"
            g03_questions = ("Q-PRC-03",)
    checks.append(GateCheck("G-03", "Choice between several valid books is defined", g03_ok, g03_detail, g03_questions))
    # G-04 unit definition confirmed
    unit_ok = bool(version.unit_definition_ref)
    checks.append(
        GateCheck(
            "G-04",
            "Unit definition confirmed",
            unit_ok,
            f"{book.unit_type}, {version.session_minutes_per_unit} minutes ({version.unit_definition_ref})"
            if unit_ok
            else "unit definition not confirmed",
            () if unit_ok else ("Q-SCH-03",),
        )
    )
    # G-05 tax treatment
    tax_ok = version.tax_treatment != "unknown"
    checks.append(
        GateCheck(
            "G-05",
            "Tax treatment set",
            tax_ok,
            f"{version.tax_treatment} ({version.tax_treatment_ref})" if tax_ok else "unknown",
            () if tax_ok else ("Q-PAY-04",),
        )
    )
    # G-06 every attached benefit approved
    pending = [d.name for b, d in benefits if b.status != "approved"]
    checks.append(
        GateCheck(
            "G-06",
            "Attached benefits reviewed and approved",
            not pending,
            "none attached (no benefit can be claimed with this price)"
            if not benefits
            else ("all approved" if not pending else f"{len(pending)} not approved: {', '.join(pending)}"),
            () if not pending else ("Q-PKG-01", "Q-PKG-04"),
        )
    )
    # G-07 approval (two different approvers while dual approval is on)
    dual = bool(settings.get_value(db, "pricing.activation.dual_approval"))
    approvals = sum(1 for p in (version.approved_by, version.second_approved_by) if p is not None)
    needed = 2 if dual else 1
    checks.append(
        GateCheck(
            "G-07",
            "Approved" + (" by two different people" if dual else ""),
            version.status in ("approved", "active") and approvals >= needed,
            f"{approvals} of {needed} approvals",
            () if approvals >= needed else ("Q-PRC-20",),
        )
    )
    # G-08 no other active version of this book (it will be superseded on activation, never overlap)
    others = db.scalar(
        select(func.count()).where(
            PriceBookVersion.price_book_id == book.id,
            PriceBookVersion.status == "active",
            PriceBookVersion.id != version.id,
        )
    )
    checks.append(
        GateCheck(
            "G-08",
            "No overlapping active version",
            True,
            "the active version will be superseded at activation" if others else "no other active version",
        )
    )
    # G-09 figures unchanged since approval, and internally valid
    problems = _entry_problems(entries)
    if version.content_hash and version.content_hash != content_hash(book, version, entries):
        problems.append("figures differ from what was approved")
    if version.status in ("approved", "active") and not version.content_hash:
        problems.append("no approval fingerprint")
    checks.append(
        GateCheck(
            "G-09",
            "Figures intact since approval",
            not problems,
            "; ".join(problems) or f"{len(entries)} entries verified",
        )
    )
    return checks


def _entry_problems(entries: list[PriceBookEntry]) -> list[str]:
    problems = []
    if not entries:
        problems.append("no entries")
    quantities = [Decimal(e.quantity) for e in entries]
    if len(set(quantities)) != len(quantities):
        problems.append("duplicate quantities")
    if any(e.package_total_minor <= 0 for e in entries):
        problems.append("non-positive total")
    return problems


# ------------------------------------------------------------------------------- lifecycle


def _record(db: Session, actor: Actor, action: str, version: PriceBookVersion, changes: dict[str, Any]) -> None:
    audit.record(db, actor, action, "price_book_version", version.id, changes)


def _require_editable(version: PriceBookVersion, what: str) -> None:
    if version.status not in EDITABLE_CONFIRMATIONS:
        raise Conflict(
            "VERSION_NOT_EDITABLE",
            f"{what} can only be recorded while the version is a draft or in review (it is {version.status}).",
        )


def confirm_figures(
    db: Session, actor: Actor, access: Access, version_id: uuid.UUID, decision_ref: str, note: str
) -> VersionView:
    """Mixt has confirmed this version's figures and the data-review points for it (G-01)."""
    access.require_somewhere("pricing.version.confirm_figures")
    ref = _decision_ref(decision_ref, "Confirming the figures")
    version = _version(db, version_id, lock=True)
    _require_editable(version, "A figures confirmation")
    if not version.figures_locked:
        raise Conflict("FIGURES_NOT_LOCKED", "Only a complete, locked set of figures can be confirmed.")
    if len(note.strip()) < 5:
        raise ValidationFailed("NOTE_REQUIRED", "Say what Mixt confirmed (e.g. which data checks were answered).")
    version.figures_confirmation = "confirmed"
    version.figures_confirmation_ref = ref
    version.figures_confirmed_by = actor.principal_id
    version.figures_confirmed_at = now_utc()
    db.flush()
    _record(db, actor, "pricing_figures_confirmed", version, {"decision_ref": ref, "note": note.strip()})
    return _view(db, version)


def set_tax_treatment(
    db: Session, actor: Actor, access: Access, version_id: uuid.UUID, treatment: str, decision_ref: str
) -> VersionView:
    access.require_somewhere("pricing.version.tax")
    if treatment not in TAX_TREATMENTS or treatment == "unknown":
        raise ValidationFailed("INVALID_TAX_TREATMENT", "Use 'inclusive', 'exclusive' or 'not_applicable'.")
    ref = _decision_ref(decision_ref, "The tax treatment")
    version = _version(db, version_id, lock=True)
    _require_editable(version, "The tax treatment")
    before = version.tax_treatment
    version.tax_treatment, version.tax_treatment_ref = treatment, ref
    db.flush()
    _record(db, actor, "pricing_tax_treatment_set", version, {"from": before, "to": treatment, "decision_ref": ref})
    return _view(db, version)


def submit(db: Session, actor: Actor, access: Access, version_id: uuid.UUID) -> VersionView:
    access.require_somewhere("pricing.version.submit")
    version = _version(db, version_id, lock=True)
    if version.status != "draft":
        raise Conflict("INVALID_TRANSITION", f"Only a draft can be submitted (this version is {version.status}).")
    if not version.figures_locked:
        raise Conflict("FIGURES_NOT_LOCKED", "Lock the figures before submitting.")
    version.status, version.submitted_by, version.submitted_at = "in_review", actor.principal_id, now_utc()
    version.approved_by = version.second_approved_by = None
    version.approved_at = version.second_approved_at = None
    db.flush()
    _record(db, actor, "pricing_version_submitted", version, {})
    return _view(db, version)


def approve(db: Session, actor: Actor, access: Access, version_id: uuid.UUID) -> VersionView:
    access.require_somewhere("pricing.version.approve")
    version = _version(db, version_id, lock=True)
    if version.status != "in_review":
        raise Conflict("INVALID_TRANSITION", f"Only a version in review can be approved (it is {version.status}).")
    if actor.principal_id == version.submitted_by:
        raise PermissionDenied("FOUR_EYES", "Someone other than the person who submitted it must approve it.")
    dual = bool(settings.get_value(db, "pricing.activation.dual_approval"))
    now = now_utc()
    if version.approved_by is None:
        version.approved_by, version.approved_at = actor.principal_id, now
    elif version.approved_by == actor.principal_id:
        raise Conflict("SECOND_APPROVER_REQUIRED", "You have already approved it; a second, different person must.")
    else:
        version.second_approved_by, version.second_approved_at = actor.principal_id, now
    approvals = sum(1 for p in (version.approved_by, version.second_approved_by) if p is not None)
    if approvals >= (2 if dual else 1):
        book = db.get(PriceBook, version.price_book_id)
        assert book is not None  # noqa: S101 (foreign key)
        version.status = "approved"
        version.content_hash = content_hash(book, version, entries_of(db, version.id))
    db.flush()
    _record(db, actor, "pricing_version_approved", version, {"approvals": approvals, "status": version.status})
    return _view(db, version)


def return_to_draft(db: Session, actor: Actor, access: Access, version_id: uuid.UUID, reason: str) -> VersionView:
    """Send back for changes (from review) or withdraw an approval (before activation)."""
    access.require_somewhere("pricing.version.approve")
    version = _version(db, version_id, lock=True)
    if version.status not in ("in_review", "approved"):
        raise Conflict("INVALID_TRANSITION", f"Only a version in review or approved can go back ({version.status}).")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    before = version.status
    version.status, version.status_reason = "draft", reason.strip()
    version.approved_by = version.second_approved_by = None
    version.approved_at = version.second_approved_at = None
    version.content_hash = None
    db.flush()
    _record(db, actor, "pricing_version_returned", version, {"from": before, "reason": reason.strip()})
    return _view(db, version)


def reject(db: Session, actor: Actor, access: Access, version_id: uuid.UUID, reason: str) -> VersionView:
    access.require_somewhere("pricing.version.approve")
    version = _version(db, version_id, lock=True)
    if version.status not in ("draft", "in_review"):
        raise Conflict("INVALID_TRANSITION", f"Only a draft or a version in review can be rejected ({version.status}).")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    version.status, version.status_reason = "rejected", reason.strip()
    db.flush()
    _record(db, actor, "pricing_version_rejected", version, {"reason": reason.strip()})
    return _view(db, version)


def activate(db: Session, actor: Actor, access: Access, version_id: uuid.UUID) -> VersionView:
    access.require_somewhere("pricing.version.activate")
    version = _version(db, version_id, lock=True)
    if version.status != "approved":
        raise Conflict("INVALID_TRANSITION", f"Only an approved version can be activated (it is {version.status}).")
    view = _view(db, version)
    failing = [c for c in view.gate if not c.ok]
    if failing:
        raise Conflict(
            "ACTIVATION_GATE_FAILED",
            "This version cannot go live yet.",
            missing=[f"{c.code} {c.title}: {c.detail}" for c in failing],
        )
    now = now_utc()
    previous = db.scalar(
        select(PriceBookVersion)
        .where(PriceBookVersion.price_book_id == version.price_book_id, PriceBookVersion.status == "active")
        .with_for_update()
    )
    if previous is not None:
        previous.status, previous.effective_to = "superseded", now
        previous.status_reason = f"Superseded by version {version.version_no}"
        db.flush()
        _record(db, actor, "pricing_version_superseded", previous, {"by_version": version.version_no})
    version.status, version.activated_by, version.activated_at, version.effective_from = (
        "active",
        actor.principal_id,
        now,
        now,
    )
    db.flush()
    _record(db, actor, "pricing_version_activated", version, {"content_hash": version.content_hash})
    return _view(db, version)


def retire(db: Session, actor: Actor, access: Access, version_id: uuid.UUID, reason: str) -> VersionView:
    access.require_somewhere("pricing.version.activate")
    version = _version(db, version_id, lock=True)
    if version.status != "active":
        raise Conflict("INVALID_TRANSITION", f"Only an active version can be retired (it is {version.status}).")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    version.status, version.status_reason, version.effective_to = "retired", reason.strip(), now_utc()
    db.flush()
    _record(db, actor, "pricing_version_retired", version, {"reason": reason.strip()})
    return _view(db, version)


# ------------------------------------------------------------------------------- corrections


@dataclass(frozen=True)
class NewEntry:
    package_code: str
    display_name: str
    quantity: Decimal
    package_total_minor: int
    advertised_unit_rate_minor: int | None = None


def anomalies(db: Session, book: PriceBook, entries: list[NewEntry]) -> list[str]:
    """Things a person should double-check (docs/04 §15). Observations only: nothing is changed."""
    notes: list[str] = []
    ordered = sorted(entries, key=lambda e: e.quantity)
    rates = [Decimal(e.package_total_minor) / e.quantity for e in ordered]
    for entry, rate in zip(ordered, rates, strict=True):
        if rate != rate.to_integral_value():
            notes.append(f"{entry.display_name}: the effective rate per {book.unit_type} is not a whole number")
    for (a, ra), (b, rb) in zip(
        zip(ordered, rates, strict=True), zip(ordered[1:], rates[1:], strict=True), strict=False
    ):
        if rb > ra:
            notes.append(f"{b.display_name}: the effective rate goes up from {a.display_name}")
        if b.package_total_minor <= a.package_total_minor:
            notes.append(f"{b.display_name}: costs no more than the smaller {a.display_name}")
    figures = {(e.quantity, e.package_total_minor) for e in entries}
    for other in db.scalars(select(PriceBook).where(PriceBook.id != book.id)):
        latest = db.scalar(
            select(PriceBookVersion)
            .where(PriceBookVersion.price_book_id == other.id)
            .order_by(PriceBookVersion.version_no.desc())
        )
        if latest is None:
            continue
        theirs = {(Decimal(e.quantity), e.package_total_minor) for e in entries_of(db, latest.id)}
        same = figures & theirs
        if same and len(same) == len(figures):
            notes.append(f"every figure is numerically identical to {other.code}")
        elif len(same) >= 2:
            notes.append(f"{len(same)} figures are numerically identical to {other.code}")
    return notes


def create_correction(
    db: Session,
    actor: Actor,
    access: Access,
    version_id: uuid.UUID,
    entries: list[NewEntry],
    source_document: str,
    source_received_on: date,
    change_summary: str,
) -> tuple[VersionView, list[str]]:
    """Load corrected figures as a new version. The corrected version is never changed (ADR-14)."""
    access.require_somewhere("pricing.version.correct")
    original = _version(db, version_id, lock=True)
    if original.status in CLOSED:
        raise Conflict("VERSION_CLOSED", f"Version {original.version_no} is {original.status}; correct the latest one.")
    if len(change_summary.strip()) < 10:
        raise ValidationFailed("CHANGE_SUMMARY_REQUIRED", "Explain the correction and who supplied it.")
    if len(source_document.strip()) < 3:
        raise ValidationFailed("SOURCE_REQUIRED", "Name the document the corrected figures come from.")
    if not entries:
        raise ValidationFailed("ENTRIES_REQUIRED", "A correction lists every package of the corrected sheet.")
    quantities = [e.quantity for e in entries]
    codes = [e.package_code for e in entries]
    if len(set(quantities)) != len(quantities) or len(set(codes)) != len(codes):
        raise ValidationFailed("DUPLICATE_PACKAGES", "Each package code and quantity may appear only once.")
    if any(e.quantity <= 0 or e.package_total_minor <= 0 for e in entries):
        raise ValidationFailed("INVALID_FIGURES", "Quantities and package totals must be positive.")
    book = db.get(PriceBook, original.price_book_id)
    assert book is not None  # noqa: S101 (foreign key)
    next_no = (
        db.scalar(select(func.max(PriceBookVersion.version_no)).where(PriceBookVersion.price_book_id == book.id)) or 0
    ) + 1
    correction = PriceBookVersion(
        price_book_id=book.id,
        version_no=next_no,
        change_type="correction",
        supersedes_version_id=original.id,
        unit_definition_ref=original.unit_definition_ref,
        session_minutes_per_unit=original.session_minutes_per_unit,
        source_document=source_document.strip(),
        source_received_on=source_received_on,
        change_summary=change_summary.strip(),
        created_by=actor.principal_id,
    )
    db.add(correction)
    db.flush()
    for i, e in enumerate(sorted(entries, key=lambda x: x.quantity)):
        db.add(
            PriceBookEntry(
                price_book_version_id=correction.id,
                package_code=e.package_code,
                display_name=e.display_name,
                quantity=e.quantity,
                package_total_minor=e.package_total_minor,
                advertised_unit_rate_minor=e.advertised_unit_rate_minor,
                sort_order=i,
            )
        )
    db.flush()
    correction.figures_locked = True
    for benefit, _definition in _benefits(db, original.id):  # same book and market: not a cross-market copy
        db.add(
            PackageBenefit(
                price_book_version_id=correction.id,
                benefit_definition_id=benefit.benefit_definition_id,
                customer_facing_text=benefit.customer_facing_text,
                sort_order=benefit.sort_order,
            )
        )
    if original.status in ("draft", "in_review", "approved"):
        original.status, original.status_reason = "rejected", f"Corrected by version {next_no}"
    db.flush()
    _record(
        db,
        actor,
        "pricing_correction_loaded",
        correction,
        {"corrects_version": original.version_no, "summary": change_summary.strip(), "entries": len(entries)},
    )
    return _view(db, correction), anomalies(db, book, entries)


# ---------------------------------------------------------------------------- assignments


def _assignment(db: Session, assignment_id: uuid.UUID) -> PriceBookMarketAssignment:
    row = db.get(PriceBookMarketAssignment, assignment_id)
    if row is None:
        raise NotFound("ASSIGNMENT_NOT_FOUND", "Market assignment not found.")
    return row


def assign_market(
    db: Session,
    actor: Actor,
    access: Access,
    book_id: uuid.UUID,
    market_id: uuid.UUID,
    decision_ref: str,
    note: str,
) -> PriceBookMarketAssignment:
    """Record Mixt's decision that a price book is used in a market (e.g. the USD schedules, Q-MKT-01)."""
    access.require_somewhere("pricing.assignments.manage")
    ref = _decision_ref(decision_ref, "Assigning a price book to a market")
    book = db.get(PriceBook, book_id)
    if book is None:
        raise NotFound("PRICE_BOOK_NOT_FOUND", "Price book not found.")
    market = reference.require_market(db, market_id)
    if market.status != "active":
        raise ValidationFailed("MARKET_NOT_ACTIVE", f"{market.name} is not an active market.")
    existing = db.scalar(
        select(PriceBookMarketAssignment).where(
            PriceBookMarketAssignment.price_book_id == book.id, PriceBookMarketAssignment.market_id == market.id
        )
    )
    if existing is not None and existing.assignment_status == "confirmed":
        raise Conflict("ALREADY_ASSIGNED", f"{book.code} is already assigned to {market.name}.")
    row = existing or PriceBookMarketAssignment(price_book_id=book.id, market_id=market.id)
    row.assignment_status, row.decision_ref = "confirmed", ref
    row.confirmed_by, row.confirmed_at, row.notes = actor.principal_id, now_utc(), note.strip() or None
    db.add(row)
    db.flush()
    audit.record(
        db, actor, "pricing_market_assigned", "price_book", book.id, {"market": market.country_code, "ref": ref}
    )
    return row


def revoke_assignment(
    db: Session, actor: Actor, access: Access, assignment_id: uuid.UUID, reason: str
) -> PriceBookMarketAssignment:
    access.require_somewhere("pricing.assignments.manage")
    row = _assignment(db, assignment_id)
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    active = db.scalar(
        select(PriceBookVersion.id).where(
            PriceBookVersion.price_book_id == row.price_book_id, PriceBookVersion.status == "active"
        )
    )
    if active is not None:
        raise Conflict("BOOK_ACTIVE", "Retire the active version before removing its market.")
    row.assignment_status, row.notes = "revoked", reason.strip()
    db.flush()
    audit.record(db, actor, "pricing_market_revoked", "price_book", row.price_book_id, {"reason": reason.strip()})
    return row


def confirm_relationship(
    db: Session, actor: Actor, access: Access, assignment_id: uuid.UUID, decision_ref: str
) -> PriceBookMarketAssignment:
    """Mixt has said how a market's schedules relate (Ireland, Q-PRC-03)."""
    access.require_somewhere("pricing.assignments.manage")
    ref = _decision_ref(decision_ref, "The relationship between the schedules")
    row = _assignment(db, assignment_id)
    if not row.requires_relationship_confirmation:
        raise Conflict("NOT_REQUIRED", "This assignment does not need a relationship confirmation.")
    row.relationship_confirmed_ref = ref
    db.flush()
    audit.record(db, actor, "pricing_relationship_confirmed", "price_book", row.price_book_id, {"ref": ref})
    return row


def approve_benefit(db: Session, actor: Actor, access: Access, benefit_id: uuid.UUID) -> PackageBenefit:
    access.require_somewhere("pricing.benefits.approve")
    benefit = db.get(PackageBenefit, benefit_id)
    if benefit is None:
        raise NotFound("BENEFIT_NOT_FOUND", "Benefit not found.")
    version = _version(db, benefit.price_book_version_id)
    _require_editable(version, "A benefit approval")
    if benefit.status == "approved":
        raise Conflict("ALREADY_APPROVED", "This benefit is already approved.")
    benefit.status, benefit.approved_by, benefit.approved_at = "approved", actor.principal_id, now_utc()
    db.flush()
    audit.record(db, actor, "pricing_benefit_approved", "package_benefit", benefit.id, {"version": str(version.id)})
    return benefit


# ---------------------------------------------------------------------------- tier selection


@dataclass(frozen=True)
class TierSelectionView:
    selection: PricingTierSelection
    book_code: str
    tier_label: str | None
    market_name: str


def _selection_view(db: Session, row: PricingTierSelection) -> TierSelectionView:
    book = db.get(PriceBook, row.price_book_id)
    assert book is not None  # noqa: S101 (foreign key)
    return TierSelectionView(row, book.code, book.tier_label, reference.require_market(db, row.market_id).name)


def books_with_active_version(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(PriceBookVersion.price_book_id).where(PriceBookVersion.status == "active")))


def tier_choices(db: Session, market_id: uuid.UUID) -> dict[str, list[PriceBook]]:
    """Per plan type, the books a person must choose between in this market (only where there is a choice)."""
    by_plan: dict[str, list[PriceBook]] = {}
    for plan in ("standard", "premium"):
        books = _competing_books(db, market_id, plan)
        if len(books) > 1:
            by_plan[plan] = books
    return by_plan


def list_tier_selections(db: Session, access: Access, account_id: uuid.UUID) -> list[TierSelectionView]:
    crm.get_account(db, access, account_id)  # visibility
    rows = db.scalars(
        select(PricingTierSelection)
        .where(PricingTierSelection.account_id == account_id)
        .order_by(PricingTierSelection.selected_at.desc(), PricingTierSelection.id.desc())
    )
    return [_selection_view(db, r) for r in rows]


def select_tier(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    price_book_id: uuid.UUID,
    reason: str,
    opportunity_id: uuid.UUID | None = None,
) -> TierSelectionView:
    """A person chooses which valid tier/schedule applies to this customer (ADR-12). Never automatic."""
    if actor.kind != "user" or actor.user_id is None:
        raise PermissionDenied("PERSON_REQUIRED", "Only a person can choose a customer's pricing tier.")
    account = crm.get_account(db, access, account_id)
    if account.market_id is None or account.market_confirmed_at is None:
        raise ValidationFailed("MARKET_NOT_CONFIRMED", "Confirm the customer's pricing market first.")
    access.require("pricing.tier.select", account.market_id)
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Say why this tier applies to this customer.")
    if opportunity_id is not None and pipeline.opportunity_account(db, opportunity_id) != account.id:
        raise ValidationFailed("OPPORTUNITY_NOT_IN_ACCOUNT", "That opportunity belongs to another customer.")
    book = db.get(PriceBook, price_book_id)
    if book is None:
        raise NotFound("PRICE_BOOK_NOT_FOUND", "Price book not found.")
    choices = tier_choices(db, account.market_id).get(book.plan_type, [])
    if book.id not in {b.id for b in choices}:
        raise ValidationFailed(
            "NOT_A_TIER_CHOICE",
            "That price book is not one of the valid tiers/schedules to choose from in this customer's market.",
        )
    previous = db.scalar(
        select(PricingTierSelection)
        .where(
            PricingTierSelection.account_id == account.id,
            PricingTierSelection.opportunity_id.is_(None)
            if opportunity_id is None
            else PricingTierSelection.opportunity_id == opportunity_id,
            PricingTierSelection.market_id == account.market_id,
            PricingTierSelection.plan_type == book.plan_type,
            PricingTierSelection.status == "active",
        )
        .with_for_update()
    )
    if previous is not None:
        previous.status = "replaced"
        db.flush()
    row = PricingTierSelection(
        account_id=account.id,
        opportunity_id=opportunity_id,
        market_id=account.market_id,
        price_book_id=book.id,
        plan_type=book.plan_type,
        reason=reason.strip(),
        selected_by_user_id=actor.user_id,
    )
    db.add(row)
    db.flush()
    if previous is not None:
        previous.replaced_by_id = row.id
        db.flush()
    audit.record(
        db,
        actor,
        "pricing_tier_selected",
        "account",
        account.id,
        {"price_book": book.code, "reason": reason.strip(), "replaced": str(previous.id) if previous else None},
    )
    return _selection_view(db, row)


def revoke_tier_selection(
    db: Session, actor: Actor, access: Access, selection_id: uuid.UUID, reason: str
) -> TierSelectionView:
    row = db.get(PricingTierSelection, selection_id)
    if row is None:
        raise NotFound("TIER_SELECTION_NOT_FOUND", "Tier selection not found.")
    crm.get_account(db, access, row.account_id)
    access.require("pricing.tier.select", row.market_id)
    if row.status != "active":
        raise Conflict("NOT_ACTIVE", "Only an active selection can be withdrawn.")
    if len(reason.strip()) < 5:
        raise ValidationFailed("REASON_REQUIRED", "Give a reason.")
    row.status = "revoked"
    db.flush()
    audit.record(db, actor, "pricing_tier_revoked", "account", row.account_id, {"reason": reason.strip()})
    return _selection_view(db, row)


def active_selection(
    db: Session, account_id: uuid.UUID, market_id: uuid.UUID, plan_type: str, opportunity_id: uuid.UUID | None
) -> PricingTierSelection | None:
    """The person's choice for this customer: the opportunity's own, else the account-wide one."""
    base = select(PricingTierSelection).where(
        PricingTierSelection.account_id == account_id,
        PricingTierSelection.market_id == market_id,
        PricingTierSelection.plan_type == plan_type,
        PricingTierSelection.status == "active",
    )
    if opportunity_id is not None:
        found = db.scalar(base.where(PricingTierSelection.opportunity_id == opportunity_id))
        if found is not None:
            return found
    return db.scalar(base.where(PricingTierSelection.opportunity_id.is_(None)))
