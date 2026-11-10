"""Opportunities: create, update, move through stages (with required checks), link students."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from mixt.core.context import Actor
from mixt.core.errors import NotFound, PermissionDenied, PreconditionFailed, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access
from mixt.modules.pipeline.models import Opportunity, OpportunityStageHistory, OpportunityStudent
from mixt.modules.pipeline.stages import StageDef, entry_stage, lost_reason_codes, stage_map
from mixt.modules.reference import service as reference

KINDS = frozenset({"new_business", "sibling_addition", "win_back"})
LATER_KINDS = frozenset({"renewal", "upsell"})  # arrive with retention (Phase 7)
FIELDS = (
    "title",
    "kind",
    "owner_user_id",
    "budget_amount_minor",
    "budget_currency",
    "budget_notes",
    "expected_close_date",
    "stage_key",
    "lost_reason_code",
    "nurture_until",
)


@dataclass
class OpportunityView:
    opportunity: Opportunity
    stage: StageDef | None
    student_ids: list[uuid.UUID]
    sla_breached: bool


def _snapshot(o: Opportunity) -> dict[str, Any]:
    return {f: getattr(o, f) for f in FIELDS}


def _students(db: Session, opportunity_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(select(OpportunityStudent.student_id).where(OpportunityStudent.opportunity_id == opportunity_id))
    )


def _view(db: Session, o: Opportunity, stages: dict[str, StageDef] | None = None) -> OpportunityView:
    stages = stages if stages is not None else stage_map(db)
    stage = stages.get(o.stage_key)
    breached = bool(
        stage
        and stage.sla_hours
        and stage.type == "open"
        and now_utc() - o.stage_entered_at > timedelta(hours=stage.sla_hours)
    )
    return OpportunityView(o, stage, _students(db, o.id), breached)


def _check_owner(db: Session, owner_user_id: uuid.UUID | None) -> None:
    if owner_user_id is not None and not identity.user_is_active(db, owner_user_id):
        raise ValidationFailed("INVALID_OWNER", "The owner must be an active user.")


def _set_students(db: Session, opportunity: Opportunity, student_ids: list[uuid.UUID]) -> None:
    if not crm.students_belong(db, opportunity.account_id, student_ids):
        raise ValidationFailed("INVALID_STUDENTS", "Every student must belong to this household.")
    db.execute(delete(OpportunityStudent).where(OpportunityStudent.opportunity_id == opportunity.id))
    for sid in dict.fromkeys(student_ids):
        db.add(OpportunityStudent(opportunity_id=opportunity.id, student_id=sid))
    db.flush()


def create_opportunity_system(
    db: Session,
    actor: Actor,
    account_id: uuid.UUID,
    title: str,
    owner_user_id: uuid.UUID | None,
    kind: str = "new_business",
    student_ids: list[uuid.UUID] | None = None,
    source_lead_id: uuid.UUID | None = None,
) -> Opportunity:
    """Trusted internal creation (lead intake). Permission checks are the caller's job."""
    if kind in LATER_KINDS:
        raise ValidationFailed("KIND_NOT_AVAILABLE_YET", f"'{kind}' opportunities arrive with retention (Phase 7).")
    if kind not in KINDS:
        raise ValidationFailed("INVALID_KIND", "Kind must be new_business, sibling_addition or win_back.")
    if not title.strip():
        raise ValidationFailed("TITLE_REQUIRED", "Give the opportunity a title.")
    _check_owner(db, owner_user_id)
    opportunity = Opportunity(
        account_id=account_id,
        stage_key=entry_stage(db).key,
        kind=kind,
        title=title.strip(),
        owner_user_id=owner_user_id,
        source_lead_id=source_lead_id,
        created_by=actor.principal_id,
    )
    db.add(opportunity)
    db.flush()
    db.add(
        OpportunityStageHistory(
            opportunity_id=opportunity.id,
            from_stage=None,
            to_stage=opportunity.stage_key,
            changed_by=actor.principal_id,
        )
    )
    _set_students(db, opportunity, student_ids or [])
    db.refresh(opportunity)
    audit.record(
        db,
        actor,
        "opportunity_created",
        "opportunity",
        opportunity.id,
        {"account_id": account_id, **audit.diff({}, _snapshot(opportunity))},
    )
    events.emit(
        db,
        actor,
        "opportunity.created",
        "opportunity",
        opportunity.id,
        {"title": opportunity.title, "stage": opportunity.stage_key},
        account_id,
    )
    return opportunity


def create_opportunity(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    title: str,
    kind: str = "new_business",
    owner_user_id: uuid.UUID | None = None,
    owner_explicit: bool = False,
    student_ids: list[uuid.UUID] | None = None,
) -> OpportunityView:
    access.require_somewhere("crm.opportunities.manage")
    account = crm.get_account(db, access, account_id)
    if owner_explicit and owner_user_id != access.user_id and not access.has_somewhere("crm.accounts.assign_owner"):
        raise PermissionDenied("PERMISSION_DENIED", "You cannot assign opportunities to other people.")
    owner = owner_user_id if owner_explicit else (account.owner_user_id or access.user_id)
    opportunity = create_opportunity_system(db, actor, account.id, title, owner, kind, student_ids)
    return _view(db, opportunity)


def _visible_query(db: Session, access: Access):  # type: ignore[no-untyped-def]
    access.require_somewhere("crm.accounts.read")
    return select(Opportunity).where(Opportunity.account_id.in_(crm.visible_account_ids(db, access)))


def get_opportunity(db: Session, access: Access, opportunity_id: uuid.UUID) -> OpportunityView:
    opportunity = db.scalar(_visible_query(db, access).where(Opportunity.id == opportunity_id))
    if opportunity is None:
        raise NotFound("OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
    return _view(db, opportunity)


def is_visible(db: Session, access: Access, opportunity_id: uuid.UUID) -> bool:
    return db.scalar(_visible_query(db, access).where(Opportunity.id == opportunity_id)) is not None


def opportunity_account(db: Session, opportunity_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(select(Opportunity.account_id).where(Opportunity.id == opportunity_id))


def list_opportunities(
    db: Session,
    access: Access,
    stage_key: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    open_only: bool = False,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[OpportunityView]:
    query = _visible_query(db, access).order_by(Opportunity.id.desc()).limit(min(max(limit, 1), 200))
    if stage_key:
        query = query.where(Opportunity.stage_key == stage_key)
    if owner_user_id:
        query = query.where(Opportunity.owner_user_id == owner_user_id)
    if account_id:
        query = query.where(Opportunity.account_id == account_id)
    if open_only:
        query = query.where(Opportunity.closed_at.is_(None))
    if before_id:
        query = query.where(Opportunity.id < before_id)
    stages = stage_map(db)
    return [_view(db, o, stages) for o in db.scalars(query)]


def open_opportunity_for_account(db: Session, account_id: uuid.UUID) -> Opportunity | None:
    return db.scalar(
        select(Opportunity)
        .where(Opportunity.account_id == account_id, Opportunity.closed_at.is_(None))
        .order_by(Opportunity.created_at.desc())
        .limit(1)
    )


def _load_for_update(
    db: Session, access: Access, opportunity_id: uuid.UUID, expected_version: int | None
) -> Opportunity:
    access.require_somewhere("crm.opportunities.manage")
    opportunity = get_opportunity(db, access, opportunity_id).opportunity
    if expected_version is None:
        raise PreconditionFailed("VERSION_REQUIRED", "Send the record version you edited (If-Match).")
    if opportunity.version != expected_version:
        raise PreconditionFailed("VERSION_MISMATCH", "This opportunity was changed by someone else; reload it.")
    return opportunity


def _flush(db: Session) -> None:
    try:
        db.flush()
    except StaleDataError as exc:
        raise PreconditionFailed(
            "VERSION_MISMATCH", "This opportunity was changed by someone else; reload it."
        ) from exc


def update_opportunity(
    db: Session,
    actor: Actor,
    access: Access,
    opportunity_id: uuid.UUID,
    expected_version: int | None,
    changes: dict[str, Any],
) -> OpportunityView:
    opportunity = _load_for_update(db, access, opportunity_id, expected_version)
    allowed = {
        "title",
        "owner_user_id",
        "budget_amount_minor",
        "budget_currency",
        "budget_notes",
        "expected_close_date",
        "student_ids",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed("UNKNOWN_FIELDS", f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    before = _snapshot(opportunity)
    if "title" in changes:
        if not str(changes["title"] or "").strip():
            raise ValidationFailed("TITLE_REQUIRED", "Give the opportunity a title.")
        opportunity.title = str(changes["title"]).strip()
    if "owner_user_id" in changes:
        if changes["owner_user_id"] != access.user_id and not access.has_somewhere("crm.accounts.assign_owner"):
            raise PermissionDenied("PERMISSION_DENIED", "You cannot assign opportunities to other people.")
        _check_owner(db, changes["owner_user_id"])
        opportunity.owner_user_id = changes["owner_user_id"]
    if "budget_amount_minor" in changes or "budget_currency" in changes:
        amount = changes.get("budget_amount_minor", opportunity.budget_amount_minor)
        currency = changes.get("budget_currency", opportunity.budget_currency)
        if (amount is None) != (currency is None):
            raise ValidationFailed("BUDGET_NEEDS_CURRENCY", "A budget needs both an amount and a currency.")
        if currency is not None and currency not in {c.code for c in reference.list_currencies(db)}:
            raise ValidationFailed("UNKNOWN_CURRENCY", f"Unknown currency '{currency}'.")
        if amount is not None and (not isinstance(amount, int) or amount < 0):
            raise ValidationFailed(
                "INVALID_AMOUNT", "Budget is a whole number of minor units (e.g. pence), not negative."
            )
        opportunity.budget_amount_minor, opportunity.budget_currency = amount, currency
    if "budget_notes" in changes:
        opportunity.budget_notes = changes["budget_notes"]
    if "expected_close_date" in changes:
        opportunity.expected_close_date = changes["expected_close_date"]
    if "student_ids" in changes:
        _set_students(db, opportunity, list(changes["student_ids"] or []))
        opportunity.updated_at = now_utc()  # bump version: student links are part of the record
    _flush(db)
    db.refresh(opportunity)
    audit.record(
        db, actor, "opportunity_updated", "opportunity", opportunity.id, audit.diff(before, _snapshot(opportunity))
    )
    return _view(db, opportunity)


def _check_requirements(
    db: Session,
    opportunity: Opportunity,
    stage: StageDef,
    note: str | None,
    lost_reason: str | None,
    nurture_until: date | None,
) -> list[str]:
    missing: list[str] = []
    for check in stage.requires:
        if check == "owner" and opportunity.owner_user_id is None:
            missing.append("an owner")
        elif check == "market_confirmed" and crm.account_for_system(db, opportunity.account_id).market_id is None:
            missing.append("a confirmed market for the household")
        elif check == "student_profile":
            problems = crm.student_profile_problems(db, opportunity.account_id, _students(db, opportunity.id))
            missing.extend(f"student profile: {p}" for p in problems)
        elif check == "note" and not (note and note.strip()):
            missing.append("a note explaining the move")
        elif check == "lost_reason" and lost_reason not in lost_reason_codes(db):
            missing.append("a lost reason from the configured list")
        elif check == "nurture_until" and (nurture_until is None or nurture_until <= date.today()):
            missing.append("a future revisit date")
    return missing


def move_stage(
    db: Session,
    actor: Actor,
    access: Access,
    opportunity_id: uuid.UUID,
    expected_version: int | None,
    to_stage: str,
    note: str | None = None,
    lost_reason: str | None = None,
    lost_notes: str | None = None,
    nurture_until: date | None = None,
) -> OpportunityView:
    opportunity = _load_for_update(db, access, opportunity_id, expected_version)
    stages = stage_map(db)
    stage = stages.get(to_stage)
    if stage is None:
        raise ValidationFailed("UNKNOWN_STAGE", f"Unknown stage '{to_stage}'.", allowed=list(stages))
    if stage.key == opportunity.stage_key:
        raise ValidationFailed("ALREADY_IN_STAGE", f"The opportunity is already in '{stage.name}'.")
    missing = _check_requirements(db, opportunity, stage, note, lost_reason, nurture_until)
    if missing:
        raise ValidationFailed(
            "STAGE_REQUIREMENTS_NOT_MET", f"To move to '{stage.name}' first add: {'; '.join(missing)}.", missing=missing
        )
    before = _snapshot(opportunity)
    from_stage = opportunity.stage_key
    opportunity.stage_key = stage.key
    opportunity.stage_entered_at = now_utc()
    opportunity.closed_at = now_utc() if stage.type in ("won", "lost") else None
    opportunity.lost_reason_code = lost_reason if stage.type == "lost" else None
    opportunity.lost_notes = lost_notes if stage.type == "lost" else None
    opportunity.nurture_until = nurture_until if "nurture_until" in stage.requires else None
    _flush(db)
    db.add(
        OpportunityStageHistory(
            opportunity_id=opportunity.id,
            from_stage=from_stage,
            to_stage=stage.key,
            note=(note or "").strip() or None,
            changed_by=actor.principal_id,
        )
    )
    qualified = stages.get("qualified")
    if qualified and stage.type != "lost" and stage.position >= qualified.position:
        crm.mark_prospect(db, actor, opportunity.account_id)
    dedupe = f"nurture-revisit:{opportunity.id}"
    if opportunity.nurture_until is not None:
        due = datetime.combine(opportunity.nurture_until, time(6, 0), tzinfo=UTC)
        events.schedule(
            db,
            actor,
            "engagement.create_task",
            {
                "title": f"Revisit: {opportunity.title}",
                "type": "follow_up",
                "account_id": opportunity.account_id,
                "opportunity_id": opportunity.id,
                "assignee_user_id": opportunity.owner_user_id,
                "dedupe_key": f"task:{dedupe}:{opportunity.nurture_until.isoformat()}",
            },
            due,
            dedupe_key=dedupe,
        )
    else:
        events.cancel(db, dedupe)
    db.refresh(opportunity)
    audit.record(
        db,
        actor,
        "opportunity_stage_changed",
        "opportunity",
        opportunity.id,
        {**audit.diff(before, _snapshot(opportunity)), "note": note},
    )
    events.emit(
        db,
        actor,
        "opportunity.stage_changed",
        "opportunity",
        opportunity.id,
        {
            "title": opportunity.title,
            "from": from_stage,
            "to": stage.key,
            "to_name": stage.name,
            "lost_reason": opportunity.lost_reason_code,
            "note": (note or "").strip() or None,
        },
        opportunity.account_id,
    )
    return _view(db, opportunity, stages)


def stage_history(db: Session, access: Access, opportunity_id: uuid.UUID) -> list[OpportunityStageHistory]:
    get_opportunity(db, access, opportunity_id)
    return list(
        db.scalars(
            select(OpportunityStageHistory)
            .where(OpportunityStageHistory.opportunity_id == opportunity_id)
            .order_by(OpportunityStageHistory.changed_at, OpportunityStageHistory.id)
        )
    )


def move_account(db: Session, from_account_id: uuid.UUID, to_account_id: uuid.UUID) -> int:
    """Re-point opportunities after a household merge (trusted internal call)."""
    result = db.execute(
        update(Opportunity)
        .where(Opportunity.account_id == from_account_id)
        .values(account_id=to_account_id, version=Opportunity.version + 1),
        execution_options={"synchronize_session": "fetch"},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
