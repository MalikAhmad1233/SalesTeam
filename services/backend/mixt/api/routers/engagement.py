"""Tasks, notes, tags, the customer timeline and failed background work."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, if_match_version, require
from mixt.core.db import get_session
from mixt.modules.engagement import service as engagement
from mixt.modules.events import service as events

router = APIRouter(tags=["engagement"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaskOut(_Out):
    id: uuid.UUID
    account_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    type: str
    title: str
    description: str | None
    due_at: datetime | None
    priority: int
    status: str
    snoozed_until: datetime | None
    assignee_user_id: uuid.UUID | None
    source: str
    completed_at: datetime | None
    created_at: datetime
    version: int


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "follow_up"
    description: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    priority: int = 2
    assignee_user_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None


class TaskPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    priority: int | None = None
    assignee_user_id: uuid.UUID | None = None


class TransitionIn(BaseModel):
    action: Literal["start", "complete", "cancel", "snooze", "reopen"]
    snooze_until: datetime | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    visibility: Literal["team", "private"] = "team"
    opportunity_id: uuid.UUID | None = None


class NoteOut(_Out):
    id: uuid.UUID
    account_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    body: str
    visibility: str
    author_principal_id: uuid.UUID
    created_at: datetime


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str | None = None


class TagOut(_Out):
    id: uuid.UUID
    name: str
    color: str | None


class ActivityOut(_Out):
    id: uuid.UUID
    type: str
    title: str
    body: str | None
    ref_type: str | None
    ref_id: str | None
    visibility: str
    actor_principal_id: uuid.UUID
    occurred_at: datetime


class DeadLetterOut(_Out):
    id: uuid.UUID
    source: str
    ref_id: uuid.UUID
    handler: str
    error: str
    failed_at: datetime
    replayed_at: datetime | None


# ------------------------------------------------------------------ tasks


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    assignee: str | None = "me",
    status: str | None = "open",
    account_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    due_before: datetime | None = None,
    limit: int = 100,
    auth: AuthContext = Depends(require("crm.tasks.manage")),
    db: Session = Depends(get_session),
) -> list[TaskOut]:
    tasks = engagement.list_tasks(db, auth.access, assignee, status, account_id, opportunity_id, due_before, limit)
    return [TaskOut.model_validate(t) for t in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskIn, auth: AuthContext = Depends(require("crm.tasks.manage")), db: Session = Depends(get_session)
) -> TaskOut:
    data: dict[str, Any] = body.model_dump(exclude_unset=True)
    data.setdefault("title", body.title)
    return TaskOut.model_validate(engagement.create_task(db, auth.actor, auth.access, data))


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: uuid.UUID,
    response: Response,
    auth: AuthContext = Depends(require("crm.tasks.manage")),
    db: Session = Depends(get_session),
) -> TaskOut:
    task = engagement.get_task(db, auth.access, task_id)
    response.headers["ETag"] = f'"{task.version}"'
    return TaskOut.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID,
    body: TaskPatchIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.tasks.manage")),
    db: Session = Depends(get_session),
) -> TaskOut:
    task = engagement.update_task(db, auth.actor, auth.access, task_id, version, body.model_dump(exclude_unset=True))
    response.headers["ETag"] = f'"{task.version}"'
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/transition", response_model=TaskOut)
def transition(
    task_id: uuid.UUID,
    body: TransitionIn,
    response: Response,
    version: int = Depends(if_match_version),
    auth: AuthContext = Depends(require("crm.tasks.manage")),
    db: Session = Depends(get_session),
) -> TaskOut:
    task = engagement.transition_task(db, auth.actor, auth.access, task_id, version, body.action, body.snooze_until)
    response.headers["ETag"] = f'"{task.version}"'
    return TaskOut.model_validate(task)


# ------------------------------------------------------------------ notes, tags, timeline


@router.get("/crm/accounts/{account_id}/notes", response_model=list[NoteOut])
def list_notes(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[NoteOut]:
    return [NoteOut.model_validate(n) for n in engagement.list_notes(db, auth.access, account_id)]


@router.post("/crm/accounts/{account_id}/notes", response_model=NoteOut, status_code=201)
def add_note(
    account_id: uuid.UUID,
    body: NoteIn,
    auth: AuthContext = Depends(require("crm.notes.write")),
    db: Session = Depends(get_session),
) -> NoteOut:
    note = engagement.add_note(db, auth.actor, auth.access, account_id, body.body, body.visibility, body.opportunity_id)
    return NoteOut.model_validate(note)


@router.get("/crm/tags", response_model=list[TagOut])
def list_tags(
    _: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[TagOut]:
    return [TagOut.model_validate(t) for t in engagement.list_tags(db)]


@router.post("/crm/tags", response_model=TagOut, status_code=201)
def create_tag(
    body: TagIn, auth: AuthContext = Depends(require("crm.tags.manage")), db: Session = Depends(get_session)
) -> TagOut:
    return TagOut.model_validate(engagement.create_tag(db, auth.actor, auth.access, body.name, body.color))


@router.get("/crm/accounts/{account_id}/tags", response_model=list[TagOut])
def account_tags(
    account_id: uuid.UUID, auth: AuthContext = Depends(require("crm.accounts.read")), db: Session = Depends(get_session)
) -> list[TagOut]:
    return [TagOut.model_validate(t) for t in engagement.account_tags(db, auth.access, account_id)]


@router.put("/crm/accounts/{account_id}/tags/{tag_id}", status_code=204)
def tag_account(
    account_id: uuid.UUID,
    tag_id: uuid.UUID,
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> None:
    engagement.tag_account(db, auth.actor, auth.access, account_id, tag_id)


@router.delete("/crm/accounts/{account_id}/tags/{tag_id}", status_code=204)
def untag_account(
    account_id: uuid.UUID,
    tag_id: uuid.UUID,
    auth: AuthContext = Depends(require("crm.accounts.update")),
    db: Session = Depends(get_session),
) -> None:
    engagement.untag_account(db, auth.actor, auth.access, account_id, tag_id)


@router.get("/crm/accounts/{account_id}/timeline", response_model=list[ActivityOut])
def timeline(
    account_id: uuid.UUID,
    before: datetime | None = None,
    limit: int = 50,
    auth: AuthContext = Depends(require("crm.accounts.read")),
    db: Session = Depends(get_session),
) -> list[ActivityOut]:
    return [ActivityOut.model_validate(a) for a in engagement.timeline(db, auth.access, account_id, before, limit)]


# ------------------------------------------------------------------ failed background work


@router.get("/ops/dead-letters", response_model=list[DeadLetterOut])
def dead_letters(
    include_replayed: bool = False,
    _: AuthContext = Depends(require("events.dead_letters.manage")),
    db: Session = Depends(get_session),
) -> list[DeadLetterOut]:
    return [DeadLetterOut.model_validate(d) for d in events.list_dead_letters(db, include_replayed)]


@router.post("/ops/dead-letters/{dead_letter_id}/replay", status_code=204)
def replay(
    dead_letter_id: uuid.UUID,
    auth: AuthContext = Depends(require("events.dead_letters.manage")),
    db: Session = Depends(get_session),
) -> None:
    events.replay_dead_letter(db, auth.actor, dead_letter_id)
