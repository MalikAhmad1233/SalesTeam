"""Opportunities and stage rules, tasks, notes, tags, timeline, outbox and scheduled actions."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mixt import cli
from mixt.core.context import SYSTEM_ACTOR
from mixt.modules.crm.models import Account
from mixt.modules.engagement.models import Activity, Task
from mixt.modules.events import service as events
from mixt.modules.events.models import DeadLetter, OutboxEvent, ScheduledAction
from mixt.modules.pipeline import service as pipeline_service
from mixt.modules.pipeline.models import Opportunity
from mixt.modules.settings.registry import STAGE_CHECKS
from tests.conftest import make_user, market_id, sign_in
from tests.test_more_paths import _NoCloseSession

OPPS = "/api/v1/pipeline/opportunities"


def _v(record: dict[str, Any]) -> dict[str, str]:
    return {"If-Match": f'"{record["version"]}"'}


def _household(api: Any) -> dict[str, Any]:
    return api.post(
        "/api/v1/leads",
        json={
            "guardian_first_name": "Huda",
            "phone": "+971 50 987 6543",
            "country": "AE",
            "student_first_name": "Rami",
        },
    ).json()


def _opp(api: Any, lead: dict[str, Any]) -> dict[str, Any]:
    return api.get(f"{OPPS}/{lead['opportunity_id']}").json()  # type: ignore[no-any-return]


def _move(api: Any, opp: dict[str, Any], to: str, **extra: Any) -> Any:
    return api.post(f"{OPPS}/{opp['id']}/move", json={"to_stage": to, **extra}, headers=_v(opp))


def test_stage_checks_are_all_implemented() -> None:
    source = inspect.getsource(pipeline_service._check_requirements)
    assert all(f'"{check}"' in source for check in STAGE_CHECKS)


def test_qualification_requires_market_and_student_profile(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    lead = _household(rep)
    opp = _opp(rep, lead)
    assert opp["stage_key"] == "new" and len(opp["student_ids"]) == 1
    moved = _move(rep, opp, "contacted")
    assert moved.status_code == 200
    opp = moved.json()
    blocked = _move(rep, opp, "qualified")
    assert blocked.status_code == 422 and blocked.json()["code"] == "STAGE_REQUIREMENTS_NOT_MET"
    missing = " ".join(blocked.json()["missing"])
    assert "confirmed market" in missing and "curriculum" in missing and "at least one subject" in missing

    account = rep.get(f"/api/v1/crm/accounts/{lead['account_id']}").json()
    rep.post(
        f"/api/v1/crm/accounts/{lead['account_id']}/market-confirmation",
        json={"market_id": str(market_id(db, "AE")), "note": "Lives in Abu Dhabi"},
        headers=_v(account),
    )
    student_id = opp["student_ids"][0]
    student = rep.get(f"/api/v1/crm/students/{student_id}").json()
    rep.patch(
        f"/api/v1/crm/students/{student_id}",
        json={"curriculum_code": "AMERICAN", "grade_text": "Grade 9"},
        headers=_v(student),
    )
    rep.post(f"/api/v1/crm/students/{student_id}/subjects", json={"subject_name": "Algebra"})
    qualified = _move(rep, opp, "qualified")
    assert qualified.status_code == 200, qualified.text
    account_row = db.get(Account, lead["account_id"])
    assert account_row is not None and account_row.lifecycle_stage == "prospect"

    no_note = _move(rep, qualified.json(), "trial_scheduled")
    assert "a note explaining the move" in no_note.json()["missing"]
    trial = _move(rep, qualified.json(), "trial_scheduled", note="Trial agreed for Tuesday")
    assert trial.status_code == 200
    history = rep.get(f"{OPPS}/{opp['id']}/history").json()
    assert [h["to_stage"] for h in history] == ["new", "contacted", "qualified", "trial_scheduled"]
    assert history[-1]["note"] == "Trial agreed for Tuesday"


def test_lost_won_and_reopen(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    opp = _opp(rep, _household(rep))
    assert "a lost reason" in " ".join(_move(rep, opp, "lost").json()["missing"])
    assert _move(rep, opp, "lost", lost_reason="unicorns").status_code == 422
    lost = _move(rep, opp, "lost", lost_reason="timing", lost_notes="Exams next year").json()
    assert lost["closed_at"] is not None and lost["lost_reason_code"] == "timing"
    reopened = _move(rep, lost, "contacted").json()
    assert reopened["closed_at"] is None and reopened["lost_reason_code"] is None
    assert _move(rep, reopened, "contacted").json()["code"] == "ALREADY_IN_STAGE"
    assert _move(rep, reopened, "teleported").json()["code"] == "UNKNOWN_STAGE"


def test_nurture_schedules_a_revisit_task(as_user: Any, db: Session) -> None:
    rep, me = as_user([("sales_rep", None)])
    opp = _opp(rep, _household(rep))
    revisit = date.today() + timedelta(days=30)
    assert _move(rep, opp, "nurture", note="Call back next term").status_code == 422  # needs a date
    nurtured = _move(rep, opp, "nurture", note="Call back next term", nurture_until=revisit.isoformat()).json()
    action = db.scalar(select(ScheduledAction).where(ScheduledAction.dedupe_key == f"nurture-revisit:{opp['id']}"))
    assert action is not None and action.status == "pending"
    # Run the worker as if the revisit date had arrived.
    result = events.run_due_actions(
        db, now=datetime.combine(revisit, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    )
    assert result.done == 1
    task = db.scalar(select(Task).where(Task.opportunity_id == opp["id"], Task.source == "system"))
    assert task is not None and task.assignee_user_id == me.id and task.title.startswith("Revisit:")
    # Leaving nurture before the date cancels the reminder.
    back = _move(rep, nurtured, "contacted").json()
    assert back["nurture_until"] is None


def test_leaving_nurture_cancels_pending_reminder(as_user: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    opp = _opp(rep, _household(rep))
    later = (date.today() + timedelta(days=60)).isoformat()
    nurtured = _move(rep, opp, "nurture", note="Later", nurture_until=later).json()
    _move(rep, nurtured, "contacted")
    action = db.scalar(select(ScheduledAction).where(ScheduledAction.dedupe_key == f"nurture-revisit:{opp['id']}"))
    assert action is not None and action.status == "cancelled"


def test_opportunity_updates_and_visibility(as_user: Any, app_factory: Any, db: Session) -> None:
    rep, _ = as_user([("sales_rep", None)])
    lead = _household(rep)
    opp = _opp(rep, lead)
    no_currency = rep.patch(f"{OPPS}/{opp['id']}", json={"budget_amount_minor": 300000}, headers=_v(opp))
    assert no_currency.json()["code"] == "BUDGET_NEEDS_CURRENCY"
    updated = rep.patch(
        f"{OPPS}/{opp['id']}",
        json={"budget_amount_minor": 300000, "budget_currency": "AED", "title": "Rami: maths support"},
        headers=_v(opp),
    )
    assert updated.status_code == 200 and updated.json()["budget_currency"] == "AED"
    stale = rep.patch(f"{OPPS}/{opp['id']}", json={"title": "Stale"}, headers=_v(opp))
    assert stale.status_code == 412
    other = sign_in(app_factory(), db, make_user(db, [("sales_rep", None)]))
    assert other.get(f"{OPPS}/{opp['id']}").status_code == 404
    assert opp["id"] not in {o["id"] for o in other.get(OPPS).json()}
    created = rep.post(OPPS, json={"account_id": lead["account_id"], "title": "Sibling", "kind": "sibling_addition"})
    assert created.status_code == 201
    assert rep.post(OPPS, json={"account_id": lead["account_id"], "title": "R", "kind": "renewal"}).json()["code"] == (
        "KIND_NOT_AVAILABLE_YET"
    )
    mine = rep.get(f"{OPPS}?account_id={lead['account_id']}&open_only=true").json()
    assert len(mine) == 2


def test_sla_breach_flag(as_user: Any, db: Session) -> None:
    admin, _ = as_user([("admin", None)])
    stages = admin.get("/api/v1/settings/crm.pipeline_stages").json()["value"]
    stages[0]["sla_hours"] = 2
    changed = admin.put("/api/v1/settings/crm.pipeline_stages", json={"value": stages, "status": "safe_default"})
    assert changed.status_code == 200, changed.text
    opp = _opp(admin, _household(admin))
    assert opp["sla_breached"] is False
    db.execute(
        update(Opportunity)
        .where(Opportunity.id == opp["id"])
        .values(stage_entered_at=datetime.now(UTC) - timedelta(hours=3))
    )
    assert admin.get(f"{OPPS}/{opp['id']}").json()["sla_breached"] is True


def test_stage_configuration_guards(as_user: Any) -> None:
    admin, _ = as_user([("admin", None)])
    _opp(admin, _household(admin))  # an opportunity now sits in "new"
    stages = admin.get("/api/v1/settings/crm.pipeline_stages").json()["value"]
    url = "/api/v1/settings/crm.pipeline_stages"
    without_new = [s for s in stages if s["key"] != "new"]
    assert admin.put(url, json={"value": without_new, "status": "safe_default"}).json()["code"] == "STAGE_IN_USE"
    dup = [*stages, stages[1]]
    assert admin.put(url, json={"value": dup, "status": "safe_default"}).json()["code"] == "DUPLICATE_STAGE_KEYS"
    no_won = [s for s in stages if s["type"] != "won"]
    assert admin.put(url, json={"value": no_won, "status": "safe_default"}).json()["code"] == "STAGES_NEED_WON_AND_LOST"
    bad_check = [{**stages[0], "requires": ["telepathy"]}, *stages[1:]]
    assert admin.put(url, json={"value": bad_check, "status": "safe_default"}).json()["code"] == "INVALID_SETTING_VALUE"
    reasons = admin.get("/api/v1/settings/crm.lost_reasons").json()["value"]
    assert {r["code"] for r in reasons} >= {"price", "timing", "other"}
    assert admin.get("/api/v1/pipeline/stages").json()[3]["requires"] == [
        "owner",
        "market_confirmed",
        "student_profile",
    ]


# ------------------------------------------------------------------ tasks, notes, tags, timeline


def test_tasks_lifecycle(as_user: Any, app_factory: Any, db: Session) -> None:
    rep, me = as_user([("sales_rep", None)])
    lead = _household(rep)
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    task = rep.post("/api/v1/tasks", json={"title": "Call Huda", "due_at": due, "account_id": lead["account_id"]})
    assert task.status_code == 201 and task.json()["assignee_user_id"] == str(me.id)
    t = task.json()
    mine = {x["id"] for x in rep.get("/api/v1/tasks").json()}
    assert t["id"] in mine
    started = rep.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "start"}, headers=_v(t)).json()
    bad_snooze = rep.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "snooze"}, headers=_v(started))
    assert bad_snooze.json()["code"] == "INVALID_SNOOZE"
    done = rep.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "complete"}, headers=_v(started)).json()
    assert done["status"] == "done" and done["completed_at"] is not None
    again = rep.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "complete"}, headers=_v(done))
    assert again.status_code == 409
    reopened = rep.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "reopen"}, headers=_v(done)).json()
    assert reopened["status"] == "open"
    edited = rep.patch(
        f"/api/v1/tasks/{t['id']}", json={"priority": 1, "title": "Call Huda today"}, headers=_v(reopened)
    )
    assert edited.json()["priority"] == 1
    assert rep.post("/api/v1/tasks", json={"title": "x", "priority": 9}).json()["code"] == "INVALID_PRIORITY"
    inactive = make_user(db, [("sales_rep", None)], status="deactivated")
    assert rep.post("/api/v1/tasks", json={"title": "x", "assignee_user_id": str(inactive.id)}).json()["code"] == (
        "INVALID_ASSIGNEE"
    )
    other = sign_in(app_factory(), db, make_user(db, [("sales_rep", None)]))
    assert other.get(f"/api/v1/tasks/{t['id']}").status_code == 404
    assert other.post("/api/v1/tasks", json={"title": "x", "account_id": lead["account_id"]}).status_code == 404


def test_notes_tags_and_timeline(as_user: Any, app_factory: Any, db: Session) -> None:
    manager, manager_user = as_user([("sales_manager", None)])
    lead = _household(manager)
    account = lead["account_id"]
    manager.post(f"/api/v1/crm/accounts/{account}/notes", json={"body": "Mother prefers WhatsApp"})
    manager.post(f"/api/v1/crm/accounts/{account}/notes", json={"body": "Private thought", "visibility": "private"})
    tag = manager.post("/api/v1/crm/tags", json={"name": "Exam year", "color": "#C2185B"}).json()
    assert manager.post("/api/v1/crm/tags", json={"name": "exam year"}).status_code == 409  # case-insensitive
    assert manager.put(f"/api/v1/crm/accounts/{account}/tags/{tag['id']}").status_code == 204
    assert [t["name"] for t in manager.get(f"/api/v1/crm/accounts/{account}/tags").json()] == ["Exam year"]
    assert (
        manager.client.delete(
            f"/api/v1/crm/accounts/{account}/tags/{tag['id']}", headers={"X-CSRF-Token": manager.csrf}
        ).status_code
        == 204
    )

    delivered = events.dispatch_outbox(db)
    assert delivered.delivered >= 5 and delivered.failed == 0
    assert events.dispatch_outbox(db).delivered == 0  # nothing left; no duplicates
    titles = [a["title"] for a in manager.get(f"/api/v1/crm/accounts/{account}/timeline").json()]
    assert "Household created" in titles and any(t.startswith("Enquiry received") for t in titles)
    assert titles.count("Note added") == 2  # the author sees both notes

    colleague = make_user(db, [("sales_manager", None)])
    other = sign_in(app_factory(), db, colleague)
    their_titles = [a["title"] for a in other.get(f"/api/v1/crm/accounts/{account}/timeline").json()]
    assert their_titles.count("Note added") == 1  # the private note is hidden
    notes = [n["body"] for n in other.get(f"/api/v1/crm/accounts/{account}/notes").json()]
    assert notes == ["Mother prefers WhatsApp"]
    assert db.scalar(select(Activity.body).where(Activity.type == "note")) is None  # note text never copied
    assert manager_user.id


# ------------------------------------------------------------------ outbox and scheduled actions


def test_failing_consumer_goes_to_dead_letter_and_can_be_replayed(as_user: Any, db: Session) -> None:
    admin, _ = as_user([("admin", None)])
    calls: list[str] = []

    def flaky(_db: Session, event: OutboxEvent) -> None:
        calls.append(event.event_type)
        raise RuntimeError("downstream unavailable")

    events.register_consumer("test.flaky", {"test.event"}, flaky)
    try:
        event = events.emit(db, SYSTEM_ACTOR, "test.event", "test", "1", {"n": 1})
        for _ in range(events.MAX_ATTEMPTS):
            events.dispatch_outbox(db)
        db.refresh(event)
        assert event.attempts == events.MAX_ATTEMPTS and event.dispatched_at is not None
        letters = admin.get("/api/v1/ops/dead-letters").json()
        letter = next(dl for dl in letters if dl["ref_id"] == str(event.id))
        assert "downstream unavailable" in letter["error"]
        assert admin.post(f"/api/v1/ops/dead-letters/{letter['id']}/replay").status_code == 204
        db.refresh(event)
        assert event.dispatched_at is None and event.attempts == 0
    finally:
        events._CONSUMERS.pop("test.flaky", None)
    rep, _ = as_user([("sales_rep", None)])
    assert rep.get("/api/v1/ops/dead-letters").status_code == 403


def test_scheduled_action_dedupe_and_unknown_handler(db: Session) -> None:
    due = datetime.now(UTC) - timedelta(minutes=1)
    first = events.schedule(db, SYSTEM_ACTOR, "nothing.handles.this", {"a": 1}, due, dedupe_key="k1")
    second = events.schedule(db, SYSTEM_ACTOR, "nothing.handles.this", {"a": 2}, due, dedupe_key="k1")
    assert first.id == second.id and second.payload == {"a": 2}
    result = events.run_due_actions(db)
    assert result.dead_lettered == 1
    db.refresh(first)
    assert first.status == "failed"
    assert db.scalar(select(DeadLetter).where(DeadLetter.ref_id == first.id)) is not None
    with pytest.raises(Exception, match="time zone"):
        events.schedule(db, SYSTEM_ACTOR, "x", {}, datetime(2030, 1, 1))


def test_cli_dispatch_and_worker(db: Session, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    events.emit(db, SYSTEM_ACTOR, "test.cli", "test", "1", {})
    monkeypatch.setattr(cli, "_sessionmaker_for", lambda _url: lambda: _NoCloseSession(db))
    assert cli.main(["dispatch-once"]) == 0
    assert "events delivered=" in capsys.readouterr().out
    assert cli.main(["worker", "--interval", "0", "--iterations", "2"]) == 0


def test_scheduling_preferences(as_user: Any) -> None:
    rep, _ = as_user([("sales_rep", None)])
    lead = _household(rep)
    student_id = _opp(rep, lead)["student_ids"][0]
    url = f"/api/v1/crm/students/{student_id}/scheduling-preferences"
    assert rep.get(url).json() is None
    ok = rep.put(
        url,
        json={
            "timezone": "Asia/Dubai",
            "preferred_weekdays": [1, 3],
            "preferred_windows": [{"start": "16:00", "end": "19:00"}],
            "lessons_per_week": 2,
        },
    )
    assert ok.status_code == 200 and ok.json()["preferred_windows"] == [{"start": "16:00", "end": "19:00"}]
    assert rep.get(url).json()["lessons_per_week"] == 2.0
    assert rep.put(url, json={"timezone": "Asia/Dubai", "preferred_weekdays": [8]}).json()["code"] == "INVALID_WEEKDAYS"
    bad_window = rep.put(
        url, json={"timezone": "Asia/Dubai", "preferred_windows": [{"start": "19:00", "end": "16:00"}]}
    )
    assert bad_window.json()["code"] == "INVALID_WINDOW"
    assert rep.put(url, json={"timezone": "Dubai"}).json()["code"] == "INVALID_TIMEZONE"


def test_task_filters_links_and_edge_cases(as_user: Any, db: Session) -> None:
    manager, me = as_user([("sales_manager", None)])
    lead = _household(manager)
    opp = _opp(manager, lead)
    soon = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    linked = manager.post("/api/v1/tasks", json={"title": "Prep trial", "opportunity_id": opp["id"], "due_at": soon})
    assert linked.status_code == 201 and linked.json()["account_id"] == lead["account_id"]
    other_household = manager.post(
        "/api/v1/leads", json={"guardian_first_name": "Noor", "phone": "+971 50 111 0000", "country": "AE"}
    ).json()
    mismatch = manager.post(
        "/api/v1/tasks", json={"title": "x", "opportunity_id": opp["id"], "account_id": other_household["account_id"]}
    )
    assert mismatch.json()["code"] == "LINK_MISMATCH"
    assert manager.post("/api/v1/tasks", json={"title": "x", "type": "party"}).json()["code"] == "INVALID_TYPE"
    pool = manager.post("/api/v1/tasks", json={"title": "Anyone", "assignee_user_id": None}).json()
    unassigned = {t["id"] for t in manager.get("/api/v1/tasks?assignee=unassigned").json()}
    assert pool["id"] in unassigned
    by_opp = manager.get(f"/api/v1/tasks?assignee=any&opportunity_id={opp['id']}").json()
    assert [t["id"] for t in by_opp] == [linked.json()["id"]]
    due_soon = manager.get(
        f"/api/v1/tasks?due_before={(datetime.now(UTC) + timedelta(days=1)).isoformat()}".replace("+", "%2B")
    )
    assert linked.json()["id"] in {t["id"] for t in due_soon.json()}
    by_user = manager.get(f"/api/v1/tasks?assignee={me.id}&status=any&account_id={lead['account_id']}").json()
    assert linked.json()["id"] in {t["id"] for t in by_user}
    t = linked.json()
    snoozed = manager.post(
        f"/api/v1/tasks/{t['id']}/transition",
        json={"action": "snooze", "snooze_until": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
        headers=_v(t),
    ).json()
    assert snoozed["status"] == "snoozed"
    cancelled = manager.post(f"/api/v1/tasks/{t['id']}/transition", json={"action": "cancel"}, headers=_v(snoozed))
    assert cancelled.json()["status"] == "cancelled"
    assert (
        manager.patch(f"/api/v1/tasks/{t['id']}", json={"status": "done"}, headers=_v(cancelled.json())).status_code
        == 422
    )
    note_bad = manager.post(f"/api/v1/crm/accounts/{lead['account_id']}/notes", json={"body": "   "})
    assert note_bad.json()["code"] == "NOTE_EMPTY"
    on_opp = manager.post(
        f"/api/v1/crm/accounts/{lead['account_id']}/notes",
        json={"body": "About the trial", "opportunity_id": opp["id"]},
    )
    assert on_opp.status_code == 201 and on_opp.json()["opportunity_id"] == opp["id"]
    assert manager.post("/api/v1/crm/tags", json={"name": "Bad", "color": "pink"}).json()["code"] == "INVALID_COLOR"
    assert manager.post("/api/v1/crm/tags", json={"name": " "}).json()["code"] == "INVALID_TAG_NAME"
    tag = manager.post("/api/v1/crm/tags", json={"name": "VIP"}).json()
    assert manager.get("/api/v1/crm/tags").json()[0]["name"] == "VIP"
    missing = manager.client.delete(
        f"/api/v1/crm/accounts/{lead['account_id']}/tags/{tag['id']}", headers={"X-CSRF-Token": manager.csrf}
    )
    assert missing.status_code == 404
    unknown_tag = manager.put(f"/api/v1/crm/accounts/{lead['account_id']}/tags/{opp['id']}")
    assert unknown_tag.status_code == 404
    page = manager.get(f"/api/v1/crm/accounts/{lead['account_id']}/timeline?limit=1").json()
    assert len(page) <= 1
    assert db.scalar(select(Task.id).where(Task.id == pool["id"])) is not None
    rep, _ = as_user([("sales_rep", None)])  # signs in on the shared client: manager requests end here
    assert rep.put(f"/api/v1/crm/accounts/{lead['account_id']}/tags/{tag['id']}").status_code == 404  # not visible


def test_opportunity_validation_branches(as_user: Any, db: Session) -> None:
    manager, _ = as_user([("sales_manager", None)])
    lead = _household(manager)
    opp = _opp(manager, lead)
    url = f"{OPPS}/{opp['id']}"
    assert manager.patch(url, json={"stage_key": "won_paid"}, headers=_v(opp)).status_code == 422  # extra=forbid
    assert manager.patch(url, json={"title": "   "}, headers=_v(opp)).json()["code"] == "TITLE_REQUIRED"
    inactive = make_user(db, [("sales_rep", None)], status="suspended")
    assert (
        manager.patch(url, json={"owner_user_id": str(inactive.id)}, headers=_v(opp)).json()["code"] == "INVALID_OWNER"
    )
    bad_currency = manager.patch(url, json={"budget_amount_minor": 100, "budget_currency": "XYZ"}, headers=_v(opp))
    assert bad_currency.json()["code"] == "UNKNOWN_CURRENCY"
    negative = manager.patch(url, json={"budget_amount_minor": -5, "budget_currency": "GBP"}, headers=_v(opp))
    assert negative.json()["code"] == "INVALID_AMOUNT"
    linked = manager.patch(
        url, json={"student_ids": [], "expected_close_date": "2027-01-31", "budget_notes": "flex"}, headers=_v(opp)
    )
    assert linked.status_code == 200 and linked.json()["student_ids"] == []
    assert manager.post(OPPS, json={"account_id": lead["account_id"], "title": "x", "kind": "party"}).json()[
        "code"
    ] == ("INVALID_KIND")
    other_student = manager.post(
        "/api/v1/leads",
        json={"guardian_first_name": "Ola", "phone": "+971 50 222 0000", "country": "AE", "student_first_name": "Tom"},
    ).json()
    foreign = _opp(manager, other_student)["student_ids"]
    wrong = manager.patch(url, json={"student_ids": foreign}, headers=_v(linked.json()))
    assert wrong.json()["code"] == "INVALID_STUDENTS"
    filtered = manager.get(f"{OPPS}?stage=new&owner_user_id={opp['owner_user_id']}&limit=5").json()
    assert all(o["stage_key"] == "new" for o in filtered)
    rep, _ = as_user([("sales_rep", None)])  # signs in on the shared client: manager requests end here
    own = rep.post(
        "/api/v1/leads", json={"guardian_first_name": "Ibrahim", "phone": "+971 50 333 0000", "country": "AE"}
    ).json()
    rep_opp = _opp(rep, own)
    assert rep.patch(f"{OPPS}/{rep_opp['id']}", json={"owner_user_id": None}, headers=_v(rep_opp)).status_code == 403
    assert (
        rep.post(OPPS, json={"account_id": own["account_id"], "title": "x", "owner_user_id": None}).status_code == 403
    )


def test_timeline_describes_every_event_type_and_lost_reason_guard(as_user: Any, db: Session) -> None:
    admin, _ = as_user([("admin", None)])
    lead = _household(admin)
    account_id = lead["account_id"]
    contact = admin.get(f"/api/v1/crm/accounts/{account_id}/contacts").json()[0]
    admin.post(
        f"/api/v1/crm/contacts/{contact['id']}/consents",
        json={
            "purpose": "marketing_email",
            "status": "granted",
            "legal_basis": "consent",
            "source": "staff_logged",
            "evidence": {"said": "yes"},
        },
    )
    account = admin.get(f"/api/v1/crm/accounts/{account_id}").json()
    admin.post(
        f"/api/v1/crm/accounts/{account_id}/market-confirmation",
        json={"market_id": str(market_id(db, "AE")), "note": "Lives in Sharjah"},
        headers=_v(account),
    )
    opp = _opp(admin, lead)
    lost = _move(admin, opp, "lost", lost_reason="price").json()
    task = admin.post("/api/v1/tasks", json={"title": "Send summary", "account_id": account_id}).json()
    admin.post(f"/api/v1/tasks/{task['id']}/transition", json={"action": "complete"}, headers=_v(task))
    events.emit(db, SYSTEM_ACTOR, "something.unusual", "test", "1", {}, lead["account_id"])
    events.dispatch_outbox(db)
    titles = [a["title"] for a in admin.get(f"/api/v1/crm/accounts/{account_id}/timeline?limit=200").json()]
    expected = [
        "Consent granted: marketing_email",
        "Pricing market confirmed: United Arab Emirates",
        "Student added: Rami",
        "Task completed: Send summary",
        "something.unusual",
    ]
    for title in expected:
        assert title in titles, title
    assert any(t.endswith("moved to Lost") for t in titles)
    reasons = admin.get("/api/v1/settings/crm.lost_reasons").json()["value"]
    without_price = [r for r in reasons if r["code"] != "price"]
    blocked = admin.put("/api/v1/settings/crm.lost_reasons", json={"value": without_price, "status": "safe_default"})
    assert blocked.json()["code"] == "LOST_REASON_IN_USE" and lost["lost_reason_code"] == "price"
    dup = admin.put(
        "/api/v1/settings/crm.lost_reasons", json={"value": [*reasons, reasons[0]], "status": "safe_default"}
    )
    assert dup.json()["code"] == "DUPLICATE_LOST_REASONS"
    first_open = [{**s} for s in admin.get("/api/v1/settings/crm.pipeline_stages").json()["value"]]
    first_open[0], first_open[-2] = first_open[-2], first_open[0]  # put "lost" first
    assert (
        admin.put("/api/v1/settings/crm.pipeline_stages", json={"value": first_open, "status": "safe_default"}).json()[
            "code"
        ]
        == "FIRST_STAGE_MUST_BE_OPEN"
    )
