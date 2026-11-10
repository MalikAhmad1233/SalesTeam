"""Event consumers owned by the engagement module: the customer timeline and scheduled tasks."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.modules.engagement.models import Activity
from mixt.modules.engagement.service import handle_create_task_action
from mixt.modules.events import service as events

TIMELINE_CONSUMER = "engagement.timeline"


def _describe(event: events.Event) -> tuple[str, str, str | None, str]:
    """(activity type, title, body, visibility) for an event. Bodies never contain note text."""
    p: dict[str, Any] = event.payload
    match event.event_type:
        case "lead.received":
            return "lead", f"Enquiry received ({p.get('source_name', p.get('source'))})", p.get("summary"), "team"
        case "account.created":
            return "system", "Household created", None, "team"
        case "account.market_confirmed":
            return "system", f"Pricing market confirmed: {p.get('market_name')}", p.get("note"), "team"
        case "account.merged":
            return "system", f"Merged with household {p.get('merged_account_number')}", None, "team"
        case "consent.recorded":
            return "consent", f"Consent {p.get('status')}: {p.get('purpose')}", f"Source: {p.get('source')}", "team"
        case "student.created":
            return "system", f"Student added: {p.get('first_name')}", None, "team"
        case "opportunity.created":
            return "stage_change", f"Opportunity opened: {p.get('title')}", None, "team"
        case "opportunity.stage_changed":
            title = f"{p.get('title')}: moved to {p.get('to_name', p.get('to'))}"
            return "stage_change", title, p.get("note"), "team"
        case "note.added":
            return "note", "Note added", None, p.get("visibility", "team")
        case "task.created":
            return "task", f"Task created: {p.get('title')}", None, "team"
        case "task.completed":
            return "task", f"Task completed: {p.get('title')}", None, "team"
        case "quotation.issued":
            return "system", f"Quotation {p.get('number')} issued: {p.get('total')}", None, "team"
        case "quotation.accepted" | "quotation.declined":
            outcome = "accepted" if event.event_type == "quotation.accepted" else "declined"
            return "system", f"Quotation {p.get('number')} {outcome}", p.get("note"), "team"
        case _:
            return "system", event.event_type, None, "team"


def timeline_consumer(db: Session, event: events.Event) -> None:
    if event.account_id is None:
        return
    if db.scalar(select(Activity.id).where(Activity.event_id == event.id)) is not None:
        return
    kind, title, body, visibility = _describe(event)
    db.add(
        Activity(
            account_id=event.account_id,
            event_id=event.id,
            type=kind,
            title=title,
            body=body,
            ref_type=event.aggregate_type,
            ref_id=event.aggregate_id,
            visibility=visibility,
            actor_principal_id=event.actor_principal_id,
            details=None,
            occurred_at=event.occurred_at,
        )
    )


def register() -> None:
    events.register_consumer(TIMELINE_CONSUMER, None, timeline_consumer)
    events.register_action_handler("engagement.create_task", handle_create_task_action)
