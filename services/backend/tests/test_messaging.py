"""Phase 3a: WhatsApp Cloud API, the integration framework and the unified inbox.

The Graph API is a fake (httpx MockTransport); webhooks are signed exactly as Meta signs them.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mixt.core import crypto
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.crm import service as crm
from mixt.modules.events import service as events
from mixt.modules.events.models import DeadLetter, ScheduledAction
from mixt.modules.identity.access import load_access
from mixt.modules.integrations import service as integrations
from mixt.modules.integrations.models import InboundWebhookEvent, IntegrationCredential
from mixt.modules.leads.models import Lead
from mixt.modules.messaging import channels, whatsapp
from mixt.modules.messaging import service as messaging
from mixt.modules.messaging.models import Conversation, Message, MessageStatusEvent, SuppressionEntry
from mixt.modules.settings import service as settings
from tests.conftest import TestUser, make_user, sign_in

APP_SECRET = "test-app-secret-0123456789"
VERIFY_TOKEN = "verify-token-0123456789abcdef"
ACCESS_TOKEN = "EAAG-test-access-token-0123456789"
PHONE_NUMBER_ID = "109876543210987"
MIXT_NUMBER = "+97444123456"
CUSTOMER = "+97455123450"


@dataclass
class FakeGraph:
    """Records requests; answers like the Graph API. Queue errors with ``fail_next``."""

    requests: list[httpx.Request] = field(default_factory=list)
    errors: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    templates: list[dict[str, Any]] = field(default_factory=list)
    counter: int = 0

    def fail_next(self, status: int, code: int | None, message: str = "error") -> None:
        body: dict[str, Any] = {"error": {"message": message, "type": "OAuthException"}}
        if code is not None:
            body["error"]["code"] = code
        self.errors.append((status, body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.errors:
            status, body = self.errors.pop(0)
            return httpx.Response(status, json=body)
        path = request.url.path
        if path.endswith("/messages"):
            self.counter += 1
            return httpx.Response(200, json={"messages": [{"id": f"wamid.out{self.counter}"}]})
        if path.endswith("/message_templates"):
            return httpx.Response(200, json={"data": self.templates, "paging": {"cursors": {}}})
        if path.endswith(f"/{PHONE_NUMBER_ID}"):
            return httpx.Response(
                200,
                json={
                    "display_phone_number": "+974 4412 3456",
                    "verified_name": "Mixt Academy",
                    "quality_rating": "GREEN",
                },
            )
        return httpx.Response(404, json={"error": {"message": "unknown path", "code": 100}})

    def sent(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/messages")]


@pytest.fixture
def graph() -> Iterator[FakeGraph]:
    fake = FakeGraph()
    whatsapp.set_transport(httpx.MockTransport(fake.handler))
    yield fake
    whatsapp.set_transport(None)


@pytest.fixture
def people(db: Session) -> dict[str, TestUser]:
    return {
        "admin": make_user(db, [("admin", None)]),
        "owner": make_user(db, [("owner", None)]),
        "manager": make_user(db, [("sales_manager", None)]),
        "rep": make_user(db, [("sales_rep", None)]),
        "rep2": make_user(db, [("sales_rep", None)]),
        "finance": make_user(db, [("finance", None)]),
    }


def _a(db: Session, user: TestUser) -> Any:
    return load_access(db, user.actor)


def _connect(db: Session, admin: TestUser, enable: bool = True) -> channels.ConnectedChannel:
    connected = channels.connect_whatsapp(
        db,
        admin.actor,
        _a(db, admin),
        channels.WhatsAppSetup(
            display_name="Mixt WhatsApp",
            graph_api_version="v21.0",
            waba_id="123456789012345",
            phone_number_id=PHONE_NUMBER_ID,
            display_phone_number=MIXT_NUMBER,
            access_token=ACCESS_TOKEN,
            app_secret=APP_SECRET,
            verify_token=VERIFY_TOKEN,
        ),
    )
    if enable:
        settings.change(
            db, admin.actor, _a(db, admin), "channels.whatsapp.numbers", [MIXT_NUMBER], "safe_default", None
        )
    return connected


def _payload(
    *messages: dict[str, Any], statuses: list[dict[str, Any]] | None = None, name: str = "Aisha"
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "97444123456", "phone_number_id": PHONE_NUMBER_ID},
    }
    if messages:
        value["contacts"] = [{"profile": {"name": name}, "wa_id": m["from"]} for m in messages]
        value["messages"] = list(messages)
    if statuses:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "123456789012345", "changes": [{"field": "messages", "value": value}]}],
    }


def _text(body: str, sender: str = CUSTOMER, msg_id: str | None = None, at: datetime | None = None) -> dict[str, Any]:
    stamp = int((at or now_utc()).timestamp())
    return {
        "from": sender.lstrip("+"),
        "id": msg_id or f"wamid.in{uuid.uuid4().hex[:12]}",
        "timestamp": str(stamp),
        "type": "text",
        "text": {"body": body},
    }


def _status(message_id: str, status: str, code: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": message_id,
        "status": status,
        "timestamp": str(int(now_utc().timestamp())),
        "recipient_id": CUSTOMER.lstrip("+"),
    }
    if code is not None:
        item["errors"] = [{"code": code, "title": "Re-engagement message"}]
    return item


def _post(client: TestClient, connection_id: uuid.UUID, payload: dict[str, Any], secret: str = APP_SECRET) -> Any:
    body = json.dumps(payload).encode()
    return client.post(
        f"/webhooks/whatsapp/{connection_id}",
        content=body,
        headers={"X-Hub-Signature-256": whatsapp.sign(secret, body), "Content-Type": "application/json"},
    )


def _deliver(client: TestClient, db: Session, connection_id: uuid.UUID, payload: dict[str, Any]) -> None:
    assert _post(client, connection_id, payload).status_code == 200
    events.run_due_actions(db)


def _conversation(db: Session, handle: str = CUSTOMER) -> Conversation:
    found = db.scalar(select(Conversation).where(Conversation.customer_handle == handle))
    assert found is not None
    return found


def _household(db: Session, rep: TestUser, number: str | None = CUSTOMER, role: str = "guardian") -> tuple[Any, Any]:
    access = _a(db, rep)
    account = crm.create_account(db, rep.actor, access, "Inbox family", country_of_residence="QA")
    contact = crm.add_contact(db, rep.actor, access, account.id, {"role": role, "first_name": "Aisha"})
    if number:
        crm.add_contact_point(db, rep.actor, access, contact.id, "whatsapp", number)
    return account, contact


# ------------------------------------------------------------------ framework and webhooks


def test_retry_delay_backs_off_and_caps() -> None:
    delays = [events.retry_delay(n).total_seconds() for n in range(1, 8)]
    assert 15 <= delays[0] <= 18 and 30 <= delays[1] <= 36 and 60 <= delays[2] <= 72
    assert all(d <= events.RETRY_MAX_SECONDS * 1.2 for d in delays) and delays[-1] >= events.RETRY_MAX_SECONDS
    assert events.retry_delay(1, hint=120).total_seconds() >= 120


def test_credentials_are_encrypted_bound_and_never_returned(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connected = _connect(db, people["admin"])
    connection_id = connected.view.connection.id
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.connection_id == connection_id, IntegrationCredential.kind == "access_token"
        )
    )
    assert row is not None and ACCESS_TOKEN.encode() not in row.ciphertext
    assert integrations.secret(db, connection_id, "access_token") == ACCESS_TOKEN
    with pytest.raises(crypto.DecryptionError):  # a ciphertext copied to another kind does not decrypt
        crypto.decrypt_text(
            crypto.EncryptedValue(row.ciphertext, row.key_id), f"integration_credential:{connection_id}:app_secret"
        )
    admin = sign_in(client, db, people["admin"])
    listed = admin.get("/api/v1/integrations")
    assert listed.status_code == 200
    for secret in (ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN):
        assert secret not in listed.text
    out = listed.json()[0]
    assert {c["kind"] for c in out["credentials"]} == {"access_token", "app_secret", "verify_token"}
    assert out["status"] == "pending" and out["webhook_path"] == f"/webhooks/whatsapp/{connection_id}"
    assert out["channel_account"]["address"] == MIXT_NUMBER and out["channel_account"]["enabled"] is True
    rotated = admin.put(
        f"/api/v1/integrations/{connection_id}/credentials",
        json={"kind": "access_token", "value": "EAAG-new-token-0000"},
    )
    assert (
        rotated.status_code == 204 and integrations.secret(db, connection_id, "access_token") == "EAAG-new-token-0000"
    )
    rep = sign_in(client, db, people["rep"])
    assert rep.get("/api/v1/integrations").status_code == 403


def test_connect_validates_and_refuses_duplicates(db: Session, people: dict[str, TestUser]) -> None:
    admin = people["admin"]
    _connect(db, admin)
    with pytest.raises(Conflict):
        _connect(db, admin)
    bad = channels.WhatsAppSetup("x", "latest", "123456789", "123456789", MIXT_NUMBER, "t" * 20, "s" * 20, "v" * 20)
    with pytest.raises(ValidationFailed, match="Graph API version"):
        channels.connect_whatsapp(db, admin.actor, _a(db, admin), bad)
    bad.graph_api_version, bad.verify_token = "v21.0", "short"
    with pytest.raises(ValidationFailed, match="verify token"):
        channels.connect_whatsapp(db, admin.actor, _a(db, admin), bad)
    with pytest.raises(Exception, match=r"integrations\.manage"):
        channels.connect_whatsapp(db, people["rep"].actor, _a(db, people["rep"]), bad)


def test_subscription_handshake(db: Session, client: TestClient, people: dict[str, TestUser]) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    url = f"/webhooks/whatsapp/{connection_id}"
    ok = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    wrong = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
    assert wrong.status_code == 403
    assert client.get(f"/webhooks/whatsapp/{uuid.uuid4()}", params={"hub.mode": "subscribe"}).status_code == 403
    connection = integrations.get_connection(db, connection_id)
    assert connection.rejected_webhooks == 1 and connection.config["webhook_verified"] is True


def test_signature_is_checked_before_anything_is_stored(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    payload = _payload(_text("Hello"))
    assert _post(client, connection_id, payload, secret="wrong-secret").status_code == 401
    body = json.dumps(payload).encode()
    tampered = client.post(
        f"/webhooks/whatsapp/{connection_id}",
        content=body.replace(b"Hello", b"Hacked"),
        headers={"X-Hub-Signature-256": whatsapp.sign(APP_SECRET, body)},
    )
    assert tampered.status_code == 401
    assert client.post(f"/webhooks/whatsapp/{connection_id}", content=body).status_code == 401  # no header
    assert db.scalar(select(InboundWebhookEvent).where(InboundWebhookEvent.connection_id == connection_id)) is None
    assert integrations.get_connection(db, connection_id).rejected_webhooks == 3
    assert _post(client, connection_id, payload).status_code == 200
    assert _post(client, connection_id, payload).status_code == 200  # Meta redelivers: stored once
    stored = list(db.scalars(select(InboundWebhookEvent).where(InboundWebhookEvent.connection_id == connection_id)))
    assert len(stored) == 1 and stored[0].status == "received"
    assert _post(client, uuid.uuid4(), payload).status_code == 404


def test_webhook_rows_and_message_history_are_guarded(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    event = db.scalar(select(InboundWebhookEvent).where(InboundWebhookEvent.connection_id == connection_id))
    assert event is not None and event.status == "processed"
    message = db.scalar(select(Message).where(Message.direction == "inbound"))
    assert message is not None
    for statement in (
        "UPDATE inbound_webhook_events SET payload = '{}'::jsonb",
        "DELETE FROM inbound_webhook_events",
        "UPDATE messages SET body_text = 'changed'",
        "DELETE FROM messages",
    ):
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(text(statement))


def test_processing_failure_retries_then_dead_letters_and_replays(
    db: Session, client: TestClient, people: dict[str, TestUser], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id

    def broken(_db: Session, _event: Any) -> str:
        raise RuntimeError("processor bug")

    monkeypatch.setitem(integrations._PROCESSORS, channels.WHATSAPP, broken)
    assert _post(client, connection_id, _payload(_text("Hello"))).status_code == 200
    later = now_utc()
    for _ in range(events.MAX_ATTEMPTS):
        later += timedelta(hours=1)  # past every backoff delay
        events.run_due_actions(db, now=later)
    event = db.scalar(select(InboundWebhookEvent).where(InboundWebhookEvent.connection_id == connection_id))
    assert event is not None and event.status == "failed" and "processor bug" in (event.last_error or "")
    assert db.scalar(select(DeadLetter).where(DeadLetter.handler == integrations.PROCESS_ACTION)) is not None
    admin = sign_in(client, db, people["admin"])
    failed = admin.get(f"/api/v1/integrations/{connection_id}/webhooks", params={"status": "failed"}).json()
    assert len(failed) == 1 and failed[0]["summary"] == "1 messages"
    assert admin.get(f"/api/v1/integrations/{connection_id}").json()["failed_webhooks"] == 1
    monkeypatch.setitem(integrations._PROCESSORS, channels.WHATSAPP, messaging.process_whatsapp)
    assert admin.post(f"/api/v1/integrations/webhooks/{event.id}/replay").status_code == 204
    events.run_due_actions(db, now=now_utc() + timedelta(minutes=1))
    db.refresh(event)
    assert event.status == "processed" and _conversation(db).unread_count == 1
    letter = db.scalar(select(DeadLetter).where(DeadLetter.handler == integrations.PROCESS_ACTION))
    assert letter is not None and letter.replayed_at is not None
    assert admin.post(f"/api/v1/integrations/webhooks/{event.id}/replay").json()["code"] == "WEBHOOK_NOT_FAILED"


# ------------------------------------------------------------------ inbound


def test_inbound_from_unknown_number_waits_in_the_unmatched_queue(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _deliver(client, db, connection_id, _payload(_text("Do you teach IGCSE maths?"), name="Aisha K"))
    conversation = _conversation(db)
    assert conversation.account_id is None and conversation.assigned_user_id is None
    assert conversation.unread_count == 1 and conversation.customer_name == "Aisha K"
    assert conversation.service_window_expires_at is not None and conversation.service_window_expires_at > now_utc()
    rep = sign_in(client, db, people["rep"])
    assert rep.get("/api/v1/inbox/conversations").json() == []  # reps don't see the unmatched queue
    assert rep.get(f"/api/v1/inbox/conversations/{conversation.id}").status_code == 404
    manager = sign_in(client, db, people["manager"])
    rows = manager.get("/api/v1/inbox/conversations", params={"view": "unmatched"}).json()
    assert [r["id"] for r in rows] == [str(conversation.id)]
    assert rows[0]["window_open"] is True and rows[0]["last_message"]["preview"] == "Do you teach IGCSE maths?"
    messages = manager.get(f"/api/v1/inbox/conversations/{conversation.id}/messages").json()
    assert [m["body_text"] for m in messages] == ["Do you teach IGCSE maths?"]
    # Link to a household the manager can see and save the number on the contact.
    account, contact = _household(db, people["rep"], number=None)
    linked = manager.post(
        f"/api/v1/inbox/conversations/{conversation.id}/link",
        json={"account_id": str(account.id), "contact_id": str(contact.id), "save_number": True},
    )
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body["account_name"] == "Inbox family" and body["assigned_user_id"] == str(people["rep"].id)
    assert crm.contact_with_point(db, account.id, "whatsapp", CUSTOMER) == contact.id
    rep = sign_in(client, db, people["rep"])
    assert [r["id"] for r in rep.get("/api/v1/inbox/conversations", params={"view": "mine"}).json()] == [
        str(conversation.id)
    ]
    assert rep.get(f"/api/v1/crm/accounts/{account.id}/conversations").json()[0]["id"] == str(conversation.id)
    finance = sign_in(client, db, people["finance"])
    assert finance.get("/api/v1/inbox/conversations").status_code == 403


def test_inbound_from_a_known_number_joins_the_household(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    account, contact = _household(db, people["rep"])
    _deliver(
        client,
        db,
        connection_id,
        _payload(
            _text("Hi, about Monday"),
            {
                "from": CUSTOMER.lstrip("+"),
                "id": "wamid.img1",
                "timestamp": str(int(now_utc().timestamp())),
                "type": "image",
                "image": {"id": "media-1", "mime_type": "image/jpeg", "sha256": "abc", "caption": "homework"},
            },
            {"from": CUSTOMER.lstrip("+"), "id": "wamid.react", "timestamp": "1", "type": "reaction", "reaction": {}},
        ),
    )
    conversation = _conversation(db)
    assert conversation.account_id == account.id and conversation.contact_id == contact.id
    assert conversation.assigned_user_id == people["rep"].id and conversation.unread_count == 2
    media = db.scalar(select(Message).where(Message.provider_message_id == "wamid.img1"))
    assert media is not None and media.content_type == "media" and media.media is not None
    assert media.media["type"] == "image" and media.media["stored"] is False and media.body_text == "homework"
    rep = sign_in(client, db, people["rep"])
    assert rep.get("/api/v1/inbox/summary").json()["unread"] == 2
    assert rep.post(f"/api/v1/inbox/conversations/{conversation.id}/read").json()["unread_count"] == 0


def test_two_households_with_the_same_number_are_not_guessed(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _household(db, people["rep"])
    _household(db, people["rep2"])
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    assert _conversation(db).account_id is None


# ------------------------------------------------------------------ sending


def _queued_text(db: Session, user: TestUser, conversation_id: uuid.UUID, body: str = "Hello Aisha") -> Any:
    return messaging.send_text(db, user.actor, _a(db, user), conversation_id, body, None)


def test_reply_inside_the_window_is_sent_and_tracked(
    db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _household(db, people["rep"])
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    rep = sign_in(client, db, people["rep"])
    sent = rep.post(
        f"/api/v1/inbox/conversations/{conversation.id}/messages",
        json={"text": "Hello Aisha, yes we do!"},
        headers={"Idempotency-Key": "reply-0001"},
    )
    assert sent.status_code == 202, sent.text
    message = sent.json()
    assert message["status"] == "queued" and message["sender_name"] == people["rep"].user.full_name
    again = rep.post(
        f"/api/v1/inbox/conversations/{conversation.id}/messages",
        json={"text": "Hello Aisha, yes we do!"},
        headers={"Idempotency-Key": "reply-0001"},
    )
    assert again.json()["id"] == message["id"]  # a retried request does not send twice
    assert events.run_due_actions(db).done == 1
    assert graph.sent() == [
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": CUSTOMER.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": "Hello Aisha, yes we do!"},
        }
    ]
    request = graph.requests[-1]
    assert request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    row = db.get(Message, uuid.UUID(message["id"]))
    assert row is not None and row.status == "sending" and row.provider_message_id == "wamid.out1"
    assert integrations.get_connection(db, connection_id).status == "connected"
    db.refresh(conversation)
    assert conversation.status == "pending_customer"
    # Statuses arrive out of order; the message never moves backwards.
    _deliver(client, db, connection_id, _payload(statuses=[_status("wamid.out1", "read")]))
    _deliver(client, db, connection_id, _payload(statuses=[_status("wamid.out1", "delivered")]))
    _deliver(client, db, connection_id, _payload(statuses=[_status("wamid.out1", "sent")]))
    db.refresh(row)
    assert row.status == "read" and row.read_at is not None and row.delivered_at is not None
    assert len(list(db.scalars(select(MessageStatusEvent).where(MessageStatusEvent.message_id == row.id)))) == 3
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE message_status_events SET status = 'failed'"))
    # The customer answers: the conversation is open again.
    _deliver(client, db, connection_id, _payload(_text("Great, thanks")))
    db.refresh(conversation)
    assert conversation.status == "open" and conversation.unread_count == 1


def test_sending_rules(db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]) -> None:
    admin, rep = people["admin"], people["rep"]
    connection_id = _connect(db, admin, enable=False).view.connection.id
    _household(db, rep)
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    with pytest.raises(ValidationFailed) as off:
        _queued_text(db, rep, conversation.id)
    assert off.value.code == "CHANNEL_OFF"
    settings.change(db, admin.actor, _a(db, admin), "channels.whatsapp.numbers", [MIXT_NUMBER], "safe_default", None)
    assert _queued_text(db, rep, conversation.id).message.status == "queued"
    # Outside the 24-hour window only templates are allowed.
    conversation.service_window_expires_at = now_utc() - timedelta(minutes=1)
    db.flush()
    with pytest.raises(ValidationFailed) as closed:
        _queued_text(db, rep, conversation.id)
    assert closed.value.code == "WINDOW_CLOSED"
    # A message queued while the window was open is not sent once it has closed.
    assert events.run_due_actions(db).done == 1
    queued = db.scalar(select(Message).where(Message.direction == "outbound"))
    assert queued is not None and queued.status == "failed" and queued.failure_code == "WINDOW_CLOSED"
    assert graph.sent() == []
    conversation.service_window_expires_at = now_utc() + timedelta(hours=1)
    db.flush()
    # A manager blocks the number: nothing is sent.
    manager = people["manager"]
    entry = messaging.suppress(db, manager.actor, _a(db, manager), "phone", CUSTOMER, "complaint", "Asked by phone")
    with pytest.raises(ValidationFailed) as blocked:
        _queued_text(db, rep, conversation.id)
    assert blocked.value.code == "RECIPIENT_SUPPRESSED"
    with pytest.raises(Conflict):
        messaging.suppress(db, manager.actor, _a(db, manager), "phone", CUSTOMER, "manual", "again")
    with pytest.raises(ValidationFailed):
        messaging.lift_suppression(db, manager.actor, _a(db, manager), entry.id, " ")
    messaging.lift_suppression(db, manager.actor, _a(db, manager), entry.id, "Customer called to ask again")
    assert _queued_text(db, rep, conversation.id).message.status == "queued"
    with pytest.raises(Exception, match=r"messaging\.suppression\.manage"):
        messaging.suppress(db, rep.actor, _a(db, rep), "phone", CUSTOMER, "manual", "x")


def test_students_are_not_messaged_directly_by_default(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    admin, rep, owner = people["admin"], people["rep"], people["owner"]
    connection_id = _connect(db, admin).view.connection.id
    account, contact = _household(db, rep, role="student")
    crm.create_student(
        db, rep.actor, _a(db, rep), account.id, {"first_name": "Omar", "contact_id": contact.id, "birth_year": 2005}
    )
    _deliver(client, db, connection_id, _payload(_text("Hi, I'm the student")))
    conversation = _conversation(db)
    with pytest.raises(ValidationFailed) as refused:
        _queued_text(db, rep, conversation.id)
    assert refused.value.code == "STUDENT_DIRECT_CONTACT_OFF"
    settings.change(
        db, owner.actor, _a(db, owner), "messaging.student_direct_contact", "enabled_from_age:18", "safe_default", None
    )
    assert _queued_text(db, rep, conversation.id).message.status == "queued"


def test_send_failures_retry_or_fail_clearly(
    db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _household(db, people["rep"])
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    rep = people["rep"]
    # Rate limited: retried later with backoff, then sent.
    first = _queued_text(db, rep, conversation.id).message
    graph.fail_next(400, 130429, "Rate limit hit")
    result = events.run_due_actions(db)
    assert result.failed == 1 and result.dead_lettered == 0
    action = db.scalar(select(ScheduledAction).where(ScheduledAction.dedupe_key == f"send:{first.id}"))
    assert action is not None and action.status == "pending" and action.due_at > now_utc() + timedelta(seconds=10)
    db.refresh(first)
    assert first.status == "queued"
    events.run_due_actions(db, now=now_utc() + timedelta(hours=1))
    db.refresh(first)
    assert first.status == "sending"
    # Not retryable: the window closed at Meta's side.
    second = _queued_text(db, rep, conversation.id).message
    graph.fail_next(400, 131047, "Re-engagement message")
    events.run_due_actions(db)
    db.refresh(second)
    assert second.status == "failed" and second.failure_code == "WINDOW_CLOSED"
    # Provider down for good: the worker gives up and the message is marked failed.
    third = _queued_text(db, rep, conversation.id).message
    later = now_utc()
    for _ in range(events.MAX_ATTEMPTS):
        graph.fail_next(503, None, "unavailable")
        later += timedelta(hours=1)
        events.run_due_actions(db, now=later)
    db.refresh(third)
    assert third.status == "failed" and third.failure_code == "SEND_GAVE_UP"
    # A person retries it as a new message; the failed one stays in the history.
    api = sign_in(client, db, rep)
    retried = api.post(f"/api/v1/inbox/messages/{third.id}/retry")
    assert retried.status_code == 202 and retried.json()["id"] != str(third.id)
    # An expired token puts the connection in error and stops further sends.
    graph.fail_next(401, 190, "Error validating access token")
    events.run_due_actions(db)
    connection = integrations.get_connection(db, connection_id)
    assert connection.status == "error" and "TOKEN_INVALID" in (connection.last_error or "")
    with pytest.raises(ValidationFailed) as unavailable:
        _queued_text(db, rep, conversation.id)
    assert unavailable.value.code == "CHANNEL_UNAVAILABLE"


def test_failed_status_from_meta_marks_the_message(
    db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _household(db, people["rep"])
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    message = _queued_text(db, people["rep"], _conversation(db).id).message
    events.run_due_actions(db)
    _deliver(client, db, connection_id, _payload(statuses=[_status("wamid.out1", "failed", code=131026)]))
    db.refresh(message)
    assert message.status == "failed" and message.failure_code == "UNDELIVERABLE"


# ------------------------------------------------------------------ opt-out keywords


def test_stop_blocks_the_number_and_start_lifts_it(
    db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _, contact = _household(db, people["rep"])
    rep = people["rep"]
    crm.record_consent(
        db,
        rep.actor,
        _a(db, rep),
        contact.id,
        "marketing_whatsapp",
        "granted",
        "consent",
        "staff_logged",
        {"note": "Parent agreed on the phone"},
    )
    _deliver(client, db, connection_id, _payload(_text("  Stop! ")))
    assert messaging.is_suppressed(db, "phone", CUSTOMER)
    entry = db.scalar(select(SuppressionEntry).where(SuppressionEntry.value == CUSTOMER))
    assert entry is not None and entry.reason == "opt_out" and entry.source == "whatsapp_keyword"
    assert crm.latest_consent_status(db, contact.id, "marketing_whatsapp") == "withdrawn"
    notes = list(db.scalars(select(Message).where(Message.sender_type == "system")))
    assert len(notes) == 1 and "stop messages" in (notes[0].body_text or "")
    with pytest.raises(ValidationFailed):
        _queued_text(db, rep, _conversation(db).id)
    _deliver(client, db, connection_id, _payload(_text("إيقاف")))  # already blocked: no second entry
    assert len(list(db.scalars(select(SuppressionEntry).where(SuppressionEntry.value == CUSTOMER)))) == 1
    _deliver(client, db, connection_id, _payload(_text("start")))
    assert not messaging.is_suppressed(db, "phone", CUSTOMER)
    assert crm.latest_consent_status(db, contact.id, "marketing_whatsapp") == "withdrawn"  # START is not consent
    assert _queued_text(db, rep, _conversation(db).id).message.status == "queued"
    # A normal message containing the word is not an opt-out.
    _deliver(client, db, connection_id, _payload(_text("Please don't stop the lessons")))
    assert not messaging.is_suppressed(db, "phone", CUSTOMER)


# ------------------------------------------------------------------ templates


TEMPLATES = [
    {
        "id": "tpl-1",
        "name": "trial_reminder",
        "language": "en",
        "status": "APPROVED",
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": "Hi {{1}}, your trial lesson is on {{2}}."}],
    },
    {
        "id": "tpl-2",
        "name": "term_offer",
        "language": "en",
        "status": "APPROVED",
        "category": "MARKETING",
        "components": [{"type": "BODY", "text": "New term places are open."}],
    },
    {
        "id": "tpl-3",
        "name": "brochure",
        "language": "en",
        "status": "APPROVED",
        "category": "MARKETING",
        "components": [{"type": "HEADER", "format": "DOCUMENT"}, {"type": "BODY", "text": "Our brochure"}],
    },
    {
        "id": "tpl-4",
        "name": "pending_one",
        "language": "ar",
        "status": "PENDING",
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": "مرحبا {{1}}"}],
    },
]


def test_templates_need_meta_and_mixt_approval_and_consent(
    db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]
) -> None:
    admin, rep = people["admin"], people["rep"]
    connection_id = _connect(db, admin).view.connection.id
    graph.templates = [dict(t) for t in TEMPLATES]
    api = sign_in(client, db, admin)
    synced = api.post(f"/api/v1/integrations/{connection_id}/templates/sync")
    assert synced.json() == {"created": 4, "updated": 0, "disabled": 0, "needs_review": 0}
    listed = {t["name"]: t for t in api.get("/api/v1/messaging/templates").json()}
    assert listed["trial_reminder"]["variable_count"] == 2
    assert listed["brochure"]["unsupported_reason"] == "it has a media or location header"
    assert listed["pending_one"]["provider_status"] == "pending"
    assert listed["trial_reminder"]["usable_problem"] == "Not approved for use at Mixt yet."
    reminder = uuid.UUID(listed["trial_reminder"]["id"])
    assert api.post(f"/api/v1/messaging/templates/{listed['brochure']['id']}/approve").json()["code"] == (
        "TEMPLATE_UNSUPPORTED"
    )
    assert api.post(f"/api/v1/messaging/templates/{listed['pending_one']['id']}/approve").json()["code"] == (
        "TEMPLATE_NOT_APPROVED_BY_META"
    )
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    conversation.service_window_expires_at = now_utc() - timedelta(hours=1)  # a business-initiated message
    db.flush()

    def send(template_id: uuid.UUID, variables: list[str]) -> Any:
        sender = people["manager"]  # the conversation starts unmatched: a manager handles it
        return messaging.send_template(db, sender.actor, _a(db, sender), conversation.id, template_id, variables, None)

    with pytest.raises(ValidationFailed, match="Not approved for use at Mixt"):
        send(reminder, ["Aisha", "Monday"])
    assert api.post(f"/api/v1/messaging/templates/{reminder}/approve").status_code == 200
    with pytest.raises(ValidationFailed) as unknown:
        send(reminder, ["Aisha", "Monday"])
    assert unknown.value.code == "CONSENT_UNKNOWN"  # not linked to a customer yet
    account, contact = _household(db, rep, number=None)
    manager = people["manager"]
    messaging.link_customer(db, manager.actor, _a(db, manager), conversation.id, account.id, contact.id, False)
    with pytest.raises(ValidationFailed) as no_consent:
        send(reminder, ["Aisha", "Monday"])
    assert no_consent.value.code == "CONSENT_REQUIRED"
    crm.record_consent(
        db,
        rep.actor,
        _a(db, rep),
        contact.id,
        "service_messages",
        "granted",
        "consent",
        "staff_logged",
        {"note": "Asked for reminders"},
    )
    with pytest.raises(ValidationFailed) as wrong_count:
        send(reminder, ["Aisha"])
    assert wrong_count.value.code == "TEMPLATE_VARIABLES"
    queued = send(reminder, ["Aisha", "Monday 4pm"]).message
    assert queued.body_text == "Hi Aisha, your trial lesson is on Monday 4pm."
    events.run_due_actions(db)
    assert graph.sent()[-1]["template"] == {
        "name": "trial_reminder",
        "language": {"code": "en"},
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": "Aisha"}, {"type": "text", "text": "Monday 4pm"}]}
        ],
    }
    # Marketing templates need WhatsApp marketing consent.
    offer = uuid.UUID(listed["term_offer"]["id"])
    channels.approve_template(db, admin.actor, _a(db, admin), offer)
    options = {t.name: problem for t, problem in messaging.templates_for(db, _a(db, rep), conversation.id)}
    assert options["term_offer"] == "No consent to WhatsApp marketing." and options["trial_reminder"] is None
    with pytest.raises(ValidationFailed, match="WhatsApp marketing"):
        send(offer, [])
    # Meta pauses a template: it cannot be sent any more.
    _deliver(
        client,
        db,
        connection_id,
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "message_template_status_update",
                            "value": {"event": "PAUSED", "message_template_id": "tpl-1", "reason": "low quality"},
                        }
                    ],
                }
            ],
        },
    )
    with pytest.raises(ValidationFailed, match="paused"):
        send(reminder, ["Aisha", "Monday"])
    # Changed wording at Meta needs a new approval at Mixt; removed templates are disabled.
    graph.templates = [dict(TEMPLATES[0], components=[{"type": "BODY", "text": "Hello {{1}}, trial on {{2}}!"}])]
    resynced = api.post(f"/api/v1/integrations/{connection_id}/templates/sync").json()
    assert resynced == {"created": 0, "updated": 1, "disabled": 3, "needs_review": 1}
    rep_api = sign_in(client, db, rep)
    assert rep_api.post(f"/api/v1/messaging/templates/{reminder}/approve").status_code == 403


def test_template_facts_are_parsed_conservatively() -> None:
    facts = whatsapp.template_facts("utility", [{"type": "BODY", "text": "Hi {{name}}"}])
    assert facts.unsupported_reason == "it uses named variables"
    gap = whatsapp.template_facts("utility", [{"type": "BODY", "text": "{{1}} and {{3}}"}])
    assert gap.unsupported_reason == "its variables are not numbered 1, 2, 3..."
    button = whatsapp.template_facts(
        "marketing",
        [
            {"type": "BODY", "text": "x"},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://mixt.example/{{1}}"}]},
        ],
    )
    assert button.unsupported_reason == "a button has a variable link"
    assert whatsapp.template_facts("authentication", [{"type": "BODY", "text": "x"}]).unsupported_reason


def test_connection_check(db: Session, client: TestClient, graph: FakeGraph, people: dict[str, TestUser]) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    api = sign_in(client, db, people["admin"])
    ok = api.post(f"/api/v1/integrations/{connection_id}/check").json()
    assert ok["ok"] is True and ok["verified_name"] == "Mixt Academy" and ok["number_matches"] is True
    graph.fail_next(401, 190, "Error validating access token")
    failed = api.post(f"/api/v1/integrations/{connection_id}/check").json()
    assert failed["ok"] is False and failed["code"] == "TOKEN_INVALID"
    assert api.get(f"/api/v1/integrations/{connection_id}").json()["status"] == "error"
    changed = api.patch(f"/api/v1/integrations/{connection_id}", json={"graph_api_version": "v22.0"})
    assert changed.json()["config"]["graph_api_version"] == "v22.0"
    disconnected = api.post(f"/api/v1/integrations/{connection_id}/disconnect").json()
    assert disconnected["status"] == "disconnected" and disconnected["credentials"] == []
    assert _post(client, connection_id, _payload(_text("Hello"))).status_code == 404


# ------------------------------------------------------------------ inbox actions


def test_assignment_notes_status_and_lead_creation(
    db: Session, client: TestClient, people: dict[str, TestUser]
) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _deliver(client, db, connection_id, _payload(_text("I'd like a tutor for my son, Grade 9 maths")))
    conversation = _conversation(db)
    manager = sign_in(client, db, people["manager"])
    assignees = {a["user_id"] for a in manager.get("/api/v1/inbox/assignees").json()}
    assert str(people["rep"].id) in assignees and str(people["finance"].id) not in assignees
    url = f"/api/v1/inbox/conversations/{conversation.id}"
    assert manager.post(f"{url}/assign", json={"user_id": str(people["finance"].id)}).json()["code"] == (
        "INVALID_ASSIGNEE"
    )
    assigned = manager.post(f"{url}/assign", json={"user_id": str(people["rep"].id)})
    assert assigned.json()["assigned_name"] == people["rep"].user.full_name
    # The assigned rep sees it even though it is not linked to a customer yet.
    rep = sign_in(client, db, people["rep"])
    assert rep.get(url).status_code == 200
    assert rep.post(f"{url}/assign", json={"user_id": str(people["rep2"].id)}).status_code == 403
    note = rep.post(f"{url}/notes", json={"text": "Called back, left a voicemail"})
    assert note.status_code == 201 and note.json()["direction"] == "internal"
    assert rep.post(f"{url}/status", json={"status": "closed"}).json()["status"] == "closed"
    assert rep.get("/api/v1/inbox/conversations", params={"status": "closed"}).json()[0]["id"] == str(conversation.id)
    assert rep.post(f"{url}/status", json={"status": "open"}).json()["status"] == "open"
    assert rep.post(f"{url}/lead", json={}).status_code == 403  # reps don't hold inbox.unmatched
    manager = sign_in(client, db, people["manager"])
    created = manager.post(f"{url}/lead", json={"guardian_first_name": "Aisha", "country": "QA"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_account"] is True and body["conversation"]["account_id"] == body["account_id"]
    lead = db.get(Lead, uuid.UUID(body["lead_id"]))
    assert lead is not None and lead.submitted_phone == CUSTOMER
    assert lead.submitted_message == "I'd like a tutor for my son, Grade 9 maths"
    assert manager.post(f"{url}/lead", json={}).json()["code"] == "ALREADY_LINKED"
    # The new household's contact has the number, so the next conversation matches by itself.
    assert crm.accounts_matching_contact_points(db, [("whatsapp", CUSTOMER)]) == [uuid.UUID(body["account_id"])]


def test_take_an_unassigned_conversation(db: Session, client: TestClient, people: dict[str, TestUser]) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    account, _ = _household(db, people["rep"])
    account.owner_user_id = None  # the unassigned pool, visible to reps
    db.flush()
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    assert conversation.assigned_user_id is None
    rep2 = sign_in(client, db, people["rep2"])
    url = f"/api/v1/inbox/conversations/{conversation.id}"
    assert [r["id"] for r in rep2.get("/api/v1/inbox/conversations", params={"view": "unassigned"}).json()] == [
        str(conversation.id)
    ]
    assert rep2.post(f"{url}/assign", json={"user_id": str(people["rep2"].id)}).status_code == 200
    assert rep2.post(f"{url}/assign", json={"user_id": None}).status_code == 403  # only managers unassign


def test_live_updates_stream(db: Session, client: TestClient, people: dict[str, TestUser]) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    manager = sign_in(client, db, people["manager"])
    response = manager.get("/api/v1/inbox/stream", params={"max_seconds": 1})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert "event: ready" in response.text and f'"id":"{conversation.id}"' in response.text
    assert response.text.count(f'"id":"{conversation.id}"') == 1  # each change is sent once
    rep = sign_in(client, db, people["rep"])
    assert str(conversation.id) not in rep.get("/api/v1/inbox/stream", params={"max_seconds": 1}).text


def test_service_level_visibility(db: Session, client: TestClient, people: dict[str, TestUser]) -> None:
    connection_id = _connect(db, people["admin"]).view.connection.id
    _household(db, people["rep"])
    _deliver(client, db, connection_id, _payload(_text("Hello")))
    conversation = _conversation(db)
    with pytest.raises(NotFound):
        messaging.view_conversation(db, _a(db, people["rep2"]), conversation.id)
    with pytest.raises(NotFound):
        messaging.link_customer(
            db, people["admin"].actor, _a(db, people["admin"]), conversation.id, uuid.uuid4(), None, False
        )
    other, other_contact = _household(db, people["rep2"], number=None)
    manager = people["manager"]
    with pytest.raises(ValidationFailed, match="Choose the contact"):
        messaging.link_customer(db, manager.actor, _a(db, manager), conversation.id, other.id, None, True)
    _, stranger = _household(db, people["rep"], number=None)
    with pytest.raises(ValidationFailed, match="does not belong"):
        messaging.link_customer(db, manager.actor, _a(db, manager), conversation.id, other.id, stranger.id, False)
    messaging.link_customer(db, manager.actor, _a(db, manager), conversation.id, other.id, other_contact.id, False)
    assert messaging.view_conversation(db, _a(db, people["rep2"]), conversation.id).account_name == "Inbox family"
    when = datetime(2030, 1, 1, tzinfo=UTC)
    assert messaging.changes_since(db, _a(db, people["rep2"]), when) == []


def test_graph_base_url_override_for_local_runs(db: Session, people: dict[str, TestUser], config_env: Any) -> None:
    connected = _connect(db, people["admin"])
    config_env(whatsapp_graph_base_url="http://localhost:8099/")
    cfg = channels.graph_config(db, connected.view.connection)
    assert cfg.base_url == "http://localhost:8099" and cfg.version == "v21.0"
