"""Lead intake, review, spreadsheet import, duplicate review and household merge.

Intake rules (docs/06 §3, BD-005, ADR-13):
- an enquiry whose phone or email already belongs to a household is linked to it ("matched");
  the household owner gets a task. Callers who cannot see that household learn only that it exists;
- otherwise a household, guardian contact, optional student and a new opportunity are created;
- an enquiry from a country outside the 13 operating markets (including the US) becomes
  ``out_of_market``: the household is flagged for a person to review and gets no opportunity;
- no pricing market is ever set by intake; no marketing consent is recorded from imports (Q-CMP-10).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.engagement import service as engagement
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access
from mixt.modules.leads import importer
from mixt.modules.leads.models import (
    Campaign,
    DuplicateCandidate,
    Lead,
    LeadImportBatch,
    LeadSource,
    RecordMerge,
)
from mixt.modules.pipeline import service as pipeline
from mixt.modules.reference import service as reference


@dataclass
class LeadInput:
    source_code: str
    guardian_first_name: str | None = None
    guardian_last_name: str | None = None
    household_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    student_first_name: str | None = None
    student_curriculum: str | None = None
    student_grade: str | None = None
    message: str | None = None
    campaign_id: uuid.UUID | None = None
    external_id: str | None = None
    utm: dict[str, Any] | None = None


@dataclass
class IntakeResult:
    lead: Lead
    account_visible: bool
    created_account: bool
    opportunity_id: uuid.UUID | None
    duplicate_candidates: int


# ------------------------------------------------------------------ sources and campaigns


def list_sources(db: Session) -> list[LeadSource]:
    return list(db.scalars(select(LeadSource).where(LeadSource.is_active).order_by(LeadSource.name)))


def _source(db: Session, code: str) -> LeadSource:
    source = db.scalar(select(LeadSource).where(LeadSource.code == code, LeadSource.is_active))
    if source is None:
        raise ValidationFailed("UNKNOWN_LEAD_SOURCE", f"Unknown lead source '{code}'.")
    return source


def create_campaign(
    db: Session, actor: Actor, access: Access, source_code: str, name: str, market_id: uuid.UUID | None = None
) -> Campaign:
    access.require_somewhere("leads.campaigns.manage")
    source = _source(db, source_code)
    clean = name.strip()
    if not clean:
        raise ValidationFailed("NAME_REQUIRED", "Give the campaign a name.")
    if market_id is not None:
        reference.require_market(db, market_id)
    if db.scalar(select(Campaign.id).where(Campaign.lead_source_id == source.id, Campaign.name == clean)):
        raise Conflict("CAMPAIGN_EXISTS", "A campaign with this name already exists for that source.")
    campaign = Campaign(lead_source_id=source.id, name=clean, market_id=market_id, created_by=actor.principal_id)
    db.add(campaign)
    db.flush()
    audit.record(db, actor, "campaign_created", "campaign", campaign.id, {"source": source_code, "name": clean})
    return campaign


def list_campaigns(db: Session) -> list[Campaign]:
    return list(db.scalars(select(Campaign).order_by(Campaign.created_at.desc())))


# ------------------------------------------------------------------ intake


def _display_name(data: LeadInput) -> str:
    if data.household_name and data.household_name.strip():
        return data.household_name.strip()
    parts = [p for p in (data.guardian_first_name, data.guardian_last_name) if p and p.strip()]
    if not parts:
        raise ValidationFailed("NAME_REQUIRED", "Give the household or guardian name.")
    return " ".join(p.strip() for p in parts)


def intake(
    db: Session,
    actor: Actor,
    access: Access,
    data: LeadInput,
    owner_user_id: uuid.UUID | None,
    owner_explicit: bool,
    import_batch_id: uuid.UUID | None = None,
    manual: bool = True,
) -> IntakeResult:
    source = _source(db, data.source_code)
    if manual and not source.manual_entry_allowed:
        raise ValidationFailed("SOURCE_NOT_MANUAL", f"Leads from '{source.code}' cannot be entered by hand.")
    display_name = _display_name(data)
    country = data.country.upper() if data.country else None
    if country is not None and not reference.country_exists(db, country):
        raise ValidationFailed("UNKNOWN_COUNTRY", f"'{data.country}' is not an ISO 3166-1 country code.")
    if data.student_curriculum and reference.curriculum_by_code(db, data.student_curriculum) is None:
        raise ValidationFailed(
            "UNKNOWN_CURRICULUM",
            f"'{data.student_curriculum}' is not a confirmed curriculum (Irish, SABIS, American, British).",
        )
    phone = normalize_phone(data.phone, country) if data.phone else None
    email = normalize_email(data.email) if data.email else None
    if phone is None and email is None:
        raise ValidationFailed("CONTACT_REQUIRED", "Give a phone number or an email address.")
    if data.campaign_id is not None:
        campaign = db.get(Campaign, data.campaign_id)
        if campaign is None or campaign.lead_source_id != source.id:
            raise ValidationFailed("INVALID_CAMPAIGN", "The campaign does not exist for this lead source.")
    if data.external_id and db.scalar(
        select(Lead.id).where(Lead.lead_source_id == source.id, Lead.external_id == data.external_id)
    ):
        raise Conflict("LEAD_ALREADY_RECEIVED", "This lead (same source and external id) was already received.")

    lead = Lead(
        lead_source_id=source.id,
        campaign_id=data.campaign_id,
        import_batch_id=import_batch_id,
        external_id=data.external_id,
        submitted_name=display_name,
        submitted_email=email,
        submitted_phone=phone,
        submitted_country=country,
        submitted_message=data.message,
        submitted_fields={k: v for k, v in data.__dict__.items() if k not in ("campaign_id", "utm") and v is not None},
        utm=data.utm,
        status="new_account",
        created_by=actor.principal_id,
    )
    db.add(lead)
    db.flush()

    points: list[tuple[str, str]] = [(k, v) for k, v in (("phone", phone), ("email", email)) if v is not None]
    matches = crm.accounts_matching_contact_points(db, points)
    opportunity_id: uuid.UUID | None = None
    duplicates = 0
    created = False
    if matches:
        account = crm.account_for_system(db, matches[0])
        lead.account_id, lead.status = account.id, "matched"
        if account.lifecycle_stage != "out_of_market":
            existing = pipeline.open_opportunity_for_account(db, account.id)
            if existing is None:
                opportunity = pipeline.create_opportunity_system(
                    db,
                    actor,
                    account.id,
                    f"{account.display_name}: new enquiry",
                    account.owner_user_id,
                    source_lead_id=lead.id,
                )
                opportunity_id = opportunity.id
            else:
                opportunity_id = existing.id
        engagement.create_system_task(
            db,
            actor,
            {
                "title": f"New enquiry from an existing household ({source.name})",
                "type": "follow_up",
                "account_id": account.id,
                "assignee_user_id": account.owner_user_id,
                "dedupe_key": f"lead:{lead.id}",
            },
        )
    else:
        created = True
        account = crm.create_account(
            db,
            actor,
            access,
            display_name,
            country_of_residence=country,
            owner_user_id=owner_user_id,
            owner_explicit=owner_explicit,
            first_touch_lead_source_id=source.id,
        )
        contact = crm.add_contact(
            db,
            actor,
            access,
            account.id,
            {
                "role": "guardian",
                "first_name": data.guardian_first_name or display_name,
                "last_name": data.guardian_last_name,
                "is_primary": True,
            },
        )
        for kind, value in points:
            crm.add_contact_point(db, actor, access, contact.id, kind, value, is_primary=True)
        student_ids: list[uuid.UUID] = []
        if data.student_first_name:
            student = crm.create_student(
                db,
                actor,
                access,
                account.id,
                {
                    "first_name": data.student_first_name,
                    "curriculum_code": data.student_curriculum,
                    "grade_text": data.student_grade,
                },
            )
            student_ids.append(student.student.id)
        lead.account_id, lead.contact_id = account.id, contact.id
        if account.lifecycle_stage == "out_of_market":
            lead.status = "out_of_market"
            lead.status_reason = f"country {country} is not an operating market"
        else:
            opportunity = pipeline.create_opportunity_system(
                db,
                actor,
                account.id,
                f"{display_name}: new enquiry",
                account.owner_user_id,
                student_ids=student_ids,
                source_lead_id=lead.id,
            )
            opportunity_id = opportunity.id
        for candidate_id, score in crm.similar_accounts(db, account.id):
            db.add(
                DuplicateCandidate(
                    account_id=account.id,
                    candidate_account_id=candidate_id,
                    reason="similar household name in the same country",
                    score=round(score, 3),
                )
            )
            duplicates += 1
    db.flush()
    audit.record(
        db,
        actor,
        "lead_received",
        "lead",
        lead.id,
        {
            "source": source.code,
            "status": lead.status,
            "account_id": lead.account_id,
            "import_batch_id": import_batch_id,
            "duplicate_candidates": duplicates,
        },
    )
    events.emit(
        db,
        actor,
        "lead.received",
        "lead",
        lead.id,
        {
            "source": source.code,
            "source_name": source.name,
            "status": lead.status,
            "summary": (data.message or "")[:280] or None,
        },
        lead.account_id,
    )
    visible = lead.account_id is not None and crm.is_visible(db, access, lead.account_id)
    return IntakeResult(lead, visible, created, opportunity_id, duplicates)


def _lead_visibility(db: Session, access: Access):  # type: ignore[no-untyped-def]
    if access.has_somewhere("leads.review"):
        return None
    return or_(Lead.account_id.in_(crm.visible_account_ids(db, access)), Lead.created_by == access.principal_id)


def list_leads(
    db: Session,
    access: Access,
    status: str | None = None,
    source_code: str | None = None,
    campaign_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Lead]:
    access.require_somewhere("leads.read")
    query = select(Lead).order_by(Lead.id.desc()).limit(min(max(limit, 1), 200))
    condition = _lead_visibility(db, access)
    if condition is not None:
        query = query.where(condition)
    if status:
        query = query.where(Lead.status == status)
    if source_code:
        query = query.where(Lead.lead_source_id == _source(db, source_code).id)
    if campaign_id:
        query = query.where(Lead.campaign_id == campaign_id)
    if before_id:
        query = query.where(Lead.id < before_id)
    return list(db.scalars(query))


def get_lead(db: Session, access: Access, lead_id: uuid.UUID) -> Lead:
    access.require_somewhere("leads.read")
    query = select(Lead).where(Lead.id == lead_id)
    condition = _lead_visibility(db, access)
    lead = db.scalar(query if condition is None else query.where(condition))
    if lead is None:
        raise NotFound("LEAD_NOT_FOUND", "Lead not found.")
    return lead


def account_visible_for(db: Session, access: Access, lead: Lead) -> bool:
    return lead.account_id is not None and crm.is_visible(db, access, lead.account_id)


def review_lead(db: Session, actor: Actor, access: Access, lead_id: uuid.UUID, decision: str, note: str) -> Lead:
    access.require_somewhere("leads.review")
    lead = get_lead(db, access, lead_id)
    if decision not in ("spam", "rejected"):
        raise ValidationFailed("INVALID_DECISION", "Decision must be 'spam' or 'rejected'.")
    if len(note.strip()) < 3:
        raise ValidationFailed("NOTE_REQUIRED", "Say why (a few words).")
    before = lead.status
    lead.status, lead.status_reason = decision, note.strip()
    lead.reviewed_by, lead.reviewed_at = actor.principal_id, now_utc()
    db.flush()
    audit.record(
        db, actor, "lead_reviewed", "lead", lead.id, {"status": {"from": before, "to": decision}, "note": note}
    )
    return lead


# ------------------------------------------------------------------ spreadsheet import


def _batch(db: Session, batch_id: uuid.UUID) -> LeadImportBatch:
    batch = db.get(LeadImportBatch, batch_id)
    if batch is None:
        raise NotFound("IMPORT_NOT_FOUND", "Import not found.")
    return batch


def validate_import(
    db: Session,
    actor: Actor,
    access: Access,
    file_name: str,
    content: bytes,
    default_owner_user_id: uuid.UUID | None,
    campaign_id: uuid.UUID | None,
) -> LeadImportBatch:
    """Step 1: check every row and store the report. Nothing is created in the CRM yet."""
    access.require_somewhere("leads.import")
    if default_owner_user_id is not None and not identity.user_is_active(db, default_owner_user_id):
        raise ValidationFailed("INVALID_OWNER", "The default owner must be an active user.")
    if campaign_id is not None:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None or campaign.lead_source_id != _source(db, "import").id:
            raise ValidationFailed("INVALID_CAMPAIGN", "Use a campaign created for the 'import' source.")
    rows = importer.parse_csv(content)
    countries = {c.code for c in reference.list_countries(db)}
    curricula = {c.code for c, _, _ in reference.list_curricula(db)}
    results = importer.validate_rows(rows, countries, curricula)
    valid = sum(r.ok for r in results)
    batch = LeadImportBatch(
        file_name=file_name[:200],
        file_sha256=hashlib.sha256(content).hexdigest(),
        status="validated",
        row_count=len(results),
        valid_count=valid,
        error_count=len(results) - valid,
        default_owner_user_id=default_owner_user_id,
        campaign_id=campaign_id,
        report={
            "rows": [r.__dict__ for r in results],
            "consents_recorded": False,
            "note": "No marketing consent is recorded from imports (Q-CMP-10).",
        },
        uploaded_by=actor.principal_id,
    )
    db.add(batch)
    db.flush()
    audit.record(
        db,
        actor,
        "lead_import_validated",
        "lead_import",
        batch.id,
        {"file_sha256": batch.file_sha256, "rows": batch.row_count, "errors": batch.error_count},
    )
    return batch


def get_import(db: Session, access: Access, batch_id: uuid.UUID) -> LeadImportBatch:
    access.require_somewhere("leads.import")
    return _batch(db, batch_id)


def _strip_personal_data(batch: LeadImportBatch, outcomes: dict[int, str]) -> None:
    rows = [
        {"row": r["row"], "ok": r["ok"], "errors": r["errors"], "outcome": outcomes.get(r["row"])}
        for r in batch.report.get("rows", [])
    ]
    batch.report = {**batch.report, "rows": rows}


def commit_import(db: Session, actor: Actor, access: Access, batch_id: uuid.UUID) -> LeadImportBatch:
    """Step 2: create leads for the valid rows. Each row runs in its own savepoint."""
    access.require_somewhere("leads.import")
    batch = _batch(db, batch_id)
    if batch.status != "validated":
        raise Conflict("IMPORT_NOT_PENDING", f"This import is already {batch.status}.")
    outcomes: dict[int, str] = {}
    imported = 0
    for row in batch.report.get("rows", []):
        if not row["ok"]:
            outcomes[row["row"]] = "skipped (invalid)"
            continue
        d = row["data"]
        data = LeadInput(
            source_code="import",
            household_name=d["household_name"],
            guardian_first_name=d["guardian_first_name"],
            guardian_last_name=d["guardian_last_name"],
            email=d["email"],
            phone=d["phone"],
            country=d["country"],
            student_first_name=d["student_first_name"],
            student_curriculum=d["student_curriculum"],
            student_grade=d["student_grade"],
            message=d["message"],
            campaign_id=batch.campaign_id,
            external_id=d["external_id"],
        )
        try:
            with db.begin_nested():
                result = intake(db, actor, access, data, batch.default_owner_user_id, True, batch.id, manual=False)
            outcomes[row["row"]] = result.lead.status
            imported += 1
        except (ValidationFailed, Conflict) as exc:
            outcomes[row["row"]] = f"failed: {exc.code}"
    batch.status, batch.imported_count = "imported", imported
    batch.finished_by, batch.finished_at = actor.principal_id, now_utc()
    _strip_personal_data(batch, outcomes)
    db.flush()
    audit.record(db, actor, "lead_import_committed", "lead_import", batch.id, {"imported": imported})
    return batch


def discard_import(db: Session, actor: Actor, access: Access, batch_id: uuid.UUID) -> LeadImportBatch:
    access.require_somewhere("leads.import")
    batch = _batch(db, batch_id)
    if batch.status != "validated":
        raise Conflict("IMPORT_NOT_PENDING", f"This import is already {batch.status}.")
    batch.status, batch.finished_by, batch.finished_at = "discarded", actor.principal_id, now_utc()
    _strip_personal_data(batch, {})
    db.flush()
    audit.record(db, actor, "lead_import_discarded", "lead_import", batch.id)
    return batch


# ------------------------------------------------------------------ duplicates and merge


def list_duplicates(db: Session, access: Access, status: str = "open") -> list[DuplicateCandidate]:
    access.require_somewhere("crm.accounts.merge")
    visible = crm.visible_account_ids(db, access)
    return list(
        db.scalars(
            select(DuplicateCandidate)
            .where(
                DuplicateCandidate.status == status,
                DuplicateCandidate.account_id.in_(visible),
                DuplicateCandidate.candidate_account_id.in_(visible),
            )
            .order_by(DuplicateCandidate.created_at.desc())
        )
    )


def dismiss_duplicate(db: Session, actor: Actor, access: Access, candidate_id: uuid.UUID) -> DuplicateCandidate:
    access.require_somewhere("crm.accounts.merge")
    candidate = db.get(DuplicateCandidate, candidate_id)
    if candidate is None or not (
        crm.is_visible(db, access, candidate.account_id) and crm.is_visible(db, access, candidate.candidate_account_id)
    ):
        raise NotFound("DUPLICATE_NOT_FOUND", "Duplicate candidate not found.")
    if candidate.status != "open":
        raise Conflict("DUPLICATE_ALREADY_RESOLVED", f"Already {candidate.status}.")
    candidate.status, candidate.resolved_by, candidate.resolved_at = "dismissed", actor.principal_id, now_utc()
    db.flush()
    audit.record(db, actor, "duplicate_dismissed", "duplicate_candidate", candidate.id)
    return candidate


def merge_accounts(
    db: Session, actor: Actor, access: Access, survivor_id: uuid.UUID, merged_id: uuid.UUID
) -> RecordMerge:
    """Merge ``merged_id`` into ``survivor_id`` across every module, in one transaction."""
    access.require_somewhere("crm.accounts.merge")
    survivor = crm.get_account(db, access, survivor_id)
    merged = crm.get_account(db, access, merged_id)
    merged_number = merged.account_number
    snapshot = crm.merge_core(db, actor, survivor.id, merged.id)
    moved_opportunities = pipeline.move_account(db, merged.id, survivor.id)
    engagement.move_account(db, merged.id, survivor.id)
    db.execute(update(Lead).where(Lead.account_id == merged.id).values(account_id=survivor.id))
    db.execute(
        update(DuplicateCandidate)
        .where(
            DuplicateCandidate.status == "open",
            or_(DuplicateCandidate.account_id == merged.id, DuplicateCandidate.candidate_account_id == merged.id),
        )
        .values(status="merged", resolved_by=actor.principal_id, resolved_at=now_utc())
    )
    record = RecordMerge(
        entity_type="account",
        surviving_id=survivor.id,
        merged_id=merged.id,
        snapshot={**snapshot, "opportunities_moved": moved_opportunities},
        merged_by=actor.principal_id,
    )
    db.add(record)
    db.flush()
    audit.record(
        db,
        actor,
        "accounts_merged",
        "account",
        survivor.id,
        {"merged_id": merged.id, "merged_account_number": merged_number},
    )
    events.emit(
        db,
        actor,
        "account.merged",
        "account",
        survivor.id,
        {"merged_id": merged.id, "merged_account_number": merged_number},
        survivor.id,
    )
    return record
