"""Tasks, notes, tags and the customer timeline.

Visibility: a task is visible to its assignee, its creator, and anyone who can see the linked
household. Notes and timeline entries follow the household, except private notes, which only
their author sees.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from mixt.core.context import SYSTEM_ACTOR, Actor
from mixt.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.engagement.models import AccountTag, Activity, Note, Tag, Task
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access
from mixt.modules.pipeline import service as pipeline

TASK_TYPES = frozenset({"follow_up", "call", "review", "data_fix", "payment_chase", "renewal", "other"})
OPEN_STATUSES = ("open", "in_progress", "snoozed")
TASK_FIELDS = ("title", "description", "due_at", "priority", "assignee_user_id", "type", "status", "snoozed_until")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# ------------------------------------------------------------------ tasks


def _validate_links(
    db: Session, access: Access | None, account_id: uuid.UUID | None, opportunity_id: uuid.UUID | None
) -> uuid.UUID | None:
    if opportunity_id is not None:
        owner_account = pipeline.opportunity_account(db, opportunity_id)
        if owner_account is None or (access is not None and not pipeline.is_visible(db, access, opportunity_id)):
            raise NotFound("OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
        if account_id is not None and account_id != owner_account:
            raise ValidationFailed("LINK_MISMATCH", "The opportunity belongs to another household.")
        account_id = owner_account
    if account_id is not None and access is not None and not crm.is_visible(db, access, account_id):
        raise NotFound("ACCOUNT_NOT_FOUND", "Account not found.")
    return account_id


def _check_task_fields(db: Session, data: dict[str, Any]) -> None:
    if "title" in data and not str(data["title"] or "").strip():
        raise ValidationFailed("TITLE_REQUIRED", "Give the task a title.")
    if "type" in data and data["type"] not in TASK_TYPES:
        raise ValidationFailed("INVALID_TYPE", f"Task type must be one of: {', '.join(sorted(TASK_TYPES))}.")
    if "priority" in data and data["priority"] not in (1, 2, 3):
        raise ValidationFailed("INVALID_PRIORITY", "Priority is 1 (high), 2 (normal) or 3 (low).")
    due = data.get("due_at")
    if isinstance(due, datetime) and due.tzinfo is None:
        raise ValidationFailed("NAIVE_DATETIME", "Due dates must include a time zone.")
    assignee = data.get("assignee_user_id")
    if assignee is not None and not identity.user_is_active(db, assignee):
        raise ValidationFailed("INVALID_ASSIGNEE", "Tasks can only be assigned to active users.")


def _create_task(db: Session, actor: Actor, data: dict[str, Any], source: str) -> Task:
    task = Task(
        account_id=data.get("account_id"),
        opportunity_id=data.get("opportunity_id"),
        type=data.get("type", "follow_up"),
        title=str(data["title"]).strip(),
        description=data.get("description"),
        due_at=data.get("due_at"),
        priority=data.get("priority", 2),
        assignee_user_id=data.get("assignee_user_id"),
        source=source,
        dedupe_key=data.get("dedupe_key"),
        created_by=actor.principal_id,
    )
    db.add(task)
    db.flush()
    db.refresh(task)
    audit.record(
        db,
        actor,
        "task_created",
        "task",
        task.id,
        {"account_id": task.account_id, **audit.diff({}, {f: getattr(task, f) for f in TASK_FIELDS})},
    )
    if task.account_id is not None:
        events.emit(
            db, actor, "task.created", "task", task.id, {"title": task.title, "source": source}, task.account_id
        )
    return task


def create_task(db: Session, actor: Actor, access: Access, data: dict[str, Any]) -> Task:
    access.require_somewhere("crm.tasks.manage")
    _check_task_fields(db, {"title": data.get("title"), **data})
    data = dict(data)
    data["account_id"] = _validate_links(db, access, data.get("account_id"), data.get("opportunity_id"))
    if "assignee_user_id" not in data:
        data["assignee_user_id"] = access.user_id
    return _create_task(db, actor, data, "manual")


def create_system_task(db: Session, actor: Actor, data: dict[str, Any]) -> Task | None:
    """Trusted internal creation (scheduled follow-ups, lead notifications). Idempotent via dedupe_key."""
    _check_task_fields(db, data)
    if data.get("dedupe_key") and db.scalar(select(Task.id).where(Task.dedupe_key == data["dedupe_key"])):
        return None
    data = dict(data)
    data["account_id"] = _validate_links(db, None, data.get("account_id"), data.get("opportunity_id"))
    return _create_task(db, actor, data, "system")


def _task_visibility(db: Session, access: Access):  # type: ignore[no-untyped-def]
    conditions = [Task.created_by == access.principal_id]
    if access.user_id is not None:
        conditions.append(Task.assignee_user_id == access.user_id)
    if access.led_team_user_ids:
        conditions.append(Task.assignee_user_id.in_(access.led_team_user_ids))
    if access.has_somewhere("crm.accounts.read"):
        conditions.append(Task.account_id.in_(crm.visible_account_ids(db, access)))
    return or_(*conditions)


def get_task(db: Session, access: Access, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, _task_visibility(db, access)))
    if task is None:
        raise NotFound("TASK_NOT_FOUND", "Task not found.")
    return task


def list_tasks(
    db: Session,
    access: Access,
    assignee: str | None = "me",
    status: str | None = "open",
    account_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    due_before: datetime | None = None,
    limit: int = 100,
) -> list[Task]:
    query = select(Task).where(_task_visibility(db, access))
    if assignee == "me":
        query = query.where(Task.assignee_user_id == access.user_id)
    elif assignee == "unassigned":
        query = query.where(Task.assignee_user_id.is_(None))
    elif assignee not in (None, "any"):
        query = query.where(Task.assignee_user_id == uuid.UUID(assignee))
    if status == "open":
        query = query.where(Task.status.in_(OPEN_STATUSES))
    elif status not in (None, "any"):
        query = query.where(Task.status == status)
    if account_id:
        query = query.where(Task.account_id == account_id)
    if opportunity_id:
        query = query.where(Task.opportunity_id == opportunity_id)
    if due_before:
        query = query.where(Task.due_at <= due_before)
    query = query.order_by(Task.due_at.asc().nulls_last(), Task.priority, Task.created_at).limit(
        min(max(limit, 1), 200)
    )
    return list(db.scalars(query))


def _load_task(db: Session, access: Access, task_id: uuid.UUID, expected_version: int | None) -> Task:
    access.require_somewhere("crm.tasks.manage")
    task = get_task(db, access, task_id)
    if expected_version is None:
        raise PreconditionFailed("VERSION_REQUIRED", "Send the record version you edited (If-Match).")
    if task.version != expected_version:
        raise PreconditionFailed("VERSION_MISMATCH", "This task was changed by someone else; reload it.")
    return task


def _save_task(db: Session, actor: Actor, task: Task, before: dict[str, Any], action: str) -> Task:
    try:
        db.flush()
    except StaleDataError as exc:
        raise PreconditionFailed("VERSION_MISMATCH", "This task was changed by someone else; reload it.") from exc
    db.refresh(task)
    audit.record(db, actor, action, "task", task.id, audit.diff(before, {f: getattr(task, f) for f in TASK_FIELDS}))
    return task


def update_task(
    db: Session, actor: Actor, access: Access, task_id: uuid.UUID, expected_version: int | None, changes: dict[str, Any]
) -> Task:
    task = _load_task(db, access, task_id, expected_version)
    allowed = {"title", "description", "due_at", "priority", "assignee_user_id", "type"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed("UNKNOWN_FIELDS", f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    _check_task_fields(db, changes)
    before = {f: getattr(task, f) for f in TASK_FIELDS}
    for key, value in changes.items():
        setattr(task, key, value.strip() if key == "title" else value)
    return _save_task(db, actor, task, before, "task_updated")


def transition_task(
    db: Session,
    actor: Actor,
    access: Access,
    task_id: uuid.UUID,
    expected_version: int | None,
    action: str,
    snooze_until: datetime | None = None,
) -> Task:
    task = _load_task(db, access, task_id, expected_version)
    before = {f: getattr(task, f) for f in TASK_FIELDS}
    is_open = task.status in OPEN_STATUSES
    if action == "start" and is_open:
        task.status, task.snoozed_until = "in_progress", None
    elif action == "complete" and is_open:
        task.status, task.completed_at, task.completed_by = "done", now_utc(), actor.principal_id
    elif action == "cancel" and is_open:
        task.status, task.completed_at, task.completed_by = "cancelled", now_utc(), actor.principal_id
    elif action == "snooze" and is_open:
        if snooze_until is None or snooze_until.tzinfo is None or snooze_until <= now_utc():
            raise ValidationFailed("INVALID_SNOOZE", "Snooze until a future time (with time zone).")
        task.status, task.snoozed_until = "snoozed", snooze_until
    elif action == "reopen" and not is_open:
        task.status, task.completed_at, task.completed_by, task.snoozed_until = "open", None, None, None
    else:
        raise Conflict("INVALID_TASK_TRANSITION", f"Cannot '{action}' a task that is '{task.status}'.")
    saved = _save_task(db, actor, task, before, f"task_{action}")
    if action == "complete" and task.account_id is not None:
        events.emit(db, actor, "task.completed", "task", task.id, {"title": task.title}, task.account_id)
    return saved


def handle_create_task_action(db: Session, action: Any) -> None:
    """Scheduled action 'engagement.create_task' (e.g. nurture revisit reminders)."""
    payload = dict(action.payload)
    for key in ("account_id", "opportunity_id", "assignee_user_id"):
        if payload.get(key):
            payload[key] = uuid.UUID(payload[key])
    payload["due_at"] = action.due_at
    create_system_task(db, SYSTEM_ACTOR, payload)


# ------------------------------------------------------------------ notes


def add_note(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    body: str,
    visibility: str = "team",
    opportunity_id: uuid.UUID | None = None,
) -> Note:
    access.require_somewhere("crm.notes.write")
    account_id_checked = _validate_links(db, access, account_id, opportunity_id) or account_id
    if visibility not in ("team", "private"):
        raise ValidationFailed("INVALID_VISIBILITY", "Visibility is 'team' or 'private'.")
    text = body.strip()
    if not text:
        raise ValidationFailed("NOTE_EMPTY", "A note needs some text.")
    if len(text) > 10_000:
        raise ValidationFailed("NOTE_TOO_LONG", "Notes are limited to 10,000 characters.")
    note = Note(
        account_id=account_id_checked,
        opportunity_id=opportunity_id,
        body=text,
        visibility=visibility,
        author_principal_id=actor.principal_id,
    )
    db.add(note)
    db.flush()
    audit.record(db, actor, "note_added", "note", note.id, {"account_id": account_id, "visibility": visibility})
    events.emit(
        db,
        actor,
        "note.added",
        "note",
        note.id,
        {"visibility": visibility, "opportunity_id": opportunity_id},
        account_id_checked,
    )
    return note


def _note_visibility(access: Access):  # type: ignore[no-untyped-def]
    return or_(Note.visibility == "team", Note.author_principal_id == access.principal_id)


def list_notes(db: Session, access: Access, account_id: uuid.UUID) -> list[Note]:
    crm.get_account(db, access, account_id)
    return list(
        db.scalars(
            select(Note).where(Note.account_id == account_id, _note_visibility(access)).order_by(Note.created_at.desc())
        )
    )


# ------------------------------------------------------------------ tags


def create_tag(db: Session, actor: Actor, access: Access, name: str, color: str | None = None) -> Tag:
    access.require_somewhere("crm.tags.manage")
    clean = name.strip()
    if not 1 <= len(clean) <= 40:
        raise ValidationFailed("INVALID_TAG_NAME", "Tag names are 1 to 40 characters.")
    if color is not None and not _COLOR.match(color):
        raise ValidationFailed("INVALID_COLOR", "Colour must look like #C2185B.")
    if db.scalar(select(Tag.id).where(Tag.name == clean)) is not None:
        raise Conflict("TAG_EXISTS", f"Tag '{clean}' already exists.")
    tag = Tag(name=clean, color=color, created_by=actor.principal_id)
    db.add(tag)
    db.flush()
    audit.record(db, actor, "tag_created", "tag", tag.id, {"name": clean})
    return tag


def list_tags(db: Session) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.name)))


def tag_account(db: Session, actor: Actor, access: Access, account_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    access.require_somewhere("crm.accounts.update")
    crm.get_account(db, access, account_id)
    if db.get(Tag, tag_id) is None:
        raise NotFound("TAG_NOT_FOUND", "Tag not found.")
    if db.get(AccountTag, (account_id, tag_id)) is None:
        db.add(AccountTag(account_id=account_id, tag_id=tag_id, tagged_by=actor.principal_id))
        db.flush()
        audit.record(db, actor, "account_tagged", "account", account_id, {"tag_id": tag_id})


def untag_account(db: Session, actor: Actor, access: Access, account_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    access.require_somewhere("crm.accounts.update")
    crm.get_account(db, access, account_id)
    result = db.execute(delete(AccountTag).where(AccountTag.account_id == account_id, AccountTag.tag_id == tag_id))
    if not result.rowcount:  # type: ignore[attr-defined]
        raise NotFound("TAG_NOT_ON_ACCOUNT", "That tag is not on this household.")
    audit.record(db, actor, "account_untagged", "account", account_id, {"tag_id": tag_id})


def account_tags(db: Session, access: Access, account_id: uuid.UUID) -> list[Tag]:
    crm.get_account(db, access, account_id)
    return list(
        db.scalars(
            select(Tag)
            .join(AccountTag, AccountTag.tag_id == Tag.id)
            .where(AccountTag.account_id == account_id)
            .order_by(Tag.name)
        )
    )


# ------------------------------------------------------------------ timeline


def timeline(
    db: Session, access: Access, account_id: uuid.UUID, before: datetime | None = None, limit: int = 50
) -> list[Activity]:
    crm.get_account(db, access, account_id)
    query = select(Activity).where(
        Activity.account_id == account_id,
        or_(Activity.visibility == "team", Activity.actor_principal_id == access.principal_id),
    )
    if before is not None:
        query = query.where(Activity.occurred_at < before)
    return list(
        db.scalars(query.order_by(Activity.occurred_at.desc(), Activity.id.desc()).limit(min(max(limit, 1), 200)))
    )


# ------------------------------------------------------------------ merges


def move_account(db: Session, from_account_id: uuid.UUID, to_account_id: uuid.UUID) -> None:
    """Re-point tasks, notes, tags and timeline entries after a household merge (trusted call)."""
    db.execute(
        update(Task)
        .where(Task.account_id == from_account_id)
        .values(account_id=to_account_id, version=Task.version + 1),
        execution_options={"synchronize_session": "fetch"},
    )
    db.execute(
        update(Note).where(Note.account_id == from_account_id).values(account_id=to_account_id),
        execution_options={"synchronize_session": "fetch"},
    )
    db.execute(
        update(Activity).where(Activity.account_id == from_account_id).values(account_id=to_account_id),
        execution_options={"synchronize_session": "fetch"},
    )
    existing = set(db.scalars(select(AccountTag.tag_id).where(AccountTag.account_id == to_account_id)))
    db.execute(delete(AccountTag).where(AccountTag.account_id == from_account_id, AccountTag.tag_id.in_(existing)))
    db.execute(
        update(AccountTag).where(AccountTag.account_id == from_account_id).values(account_id=to_account_id),
        execution_options={"synchronize_session": "fetch"},
    )
