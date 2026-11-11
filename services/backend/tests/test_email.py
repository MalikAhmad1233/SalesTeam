"""Phase 3b: email over IMAP/SMTP (BD-034), against a local IMAP server and a real SMTP server."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.errors import ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.crm import service as crm
from mixt.modules.events import service as events
from mixt.modules.events.models import ScheduledAction
from mixt.modules.identity.access import load_access
from mixt.modules.integrations import service as integrations
from mixt.modules.leads.models import Lead
from mixt.modules.messaging import channels, email_channel
from mixt.modules.messaging import service as messaging
from mixt.modules.messaging.models import Conversation, Message, SuppressionEntry
from mixt.modules.settings import service as settings
from tests.conftest import TestUser, make_user, sign_in
from tests.mail_servers import PASSWORD, USER, FakeImap, FakeSmtp

CUSTOMER = "aisha.khan@example.com"


@pytest.fixture
def imap() -> Iterator[FakeImap]:
    server = FakeImap()
    yield server
    server.stop()


@pytest.fixture
def smtp() -> Iterator[FakeSmtp]:
    server = FakeSmtp()
    yield server
    server.stop()


@pytest.fixture
def people(db: Session) -> dict[str, TestUser]:
    return {
        "admin": make_user(db, [("admin", None)]),
        "manager": make_user(db, [("sales_manager", None)]),
        "rep": make_user(db, [("sales_rep", None)]),
    }


def _a(db: Session, user: TestUser) -> Any:
    return load_access(db, user.actor)


def _setup(imap: FakeImap, smtp_port: int, password: str = PASSWORD) -> channels.MailboxSetup:
    return channels.MailboxSetup(
        display_name="Mixt Sales",
        address=USER,
        username=USER,
        password=password,
        imap_host="127.0.0.1",
        imap_port=imap.port,
        imap_security="none",
        smtp_host="127.0.0.1",
        smtp_port=smtp_port,
        smtp_security="none",
    )


def _connect(db: Session, admin: TestUser, imap: FakeImap, smtp_port: int, enable: bool = True) -> Any:
    connected = channels.connect_mailbox(db, admin.actor, _a(db, admin), _setup(imap, smtp_port))
    if enable:
        access = _a(db, admin)
        settings.change(db, admin.actor, access, "channels.email.provider", "imap_smtp", "safe_default", None)
        settings.change(db, admin.actor, access, "channels.email.mailboxes", [USER], "safe_default", None)
    return connected


def _email(
    body: str = "Hello, do you offer IGCSE Physics?",
    subject: str = "IGCSE Physics tutoring",
    sender: str = f"Aisha Khan <{CUSTOMER}>",
    message_id: str | None = None,
    headers: dict[str, str] | None = None,
    html: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"Mixt Sales <{USER}>"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(now_utc())
    msg["Message-ID"] = message_id or make_msgid(domain="example.com")
    for key, value in (headers or {}).items():
        msg[key] = value
    if html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
    return bytes(msg)


def _receive(db: Session, imap: FakeImap, raw: bytes) -> None:
    imap.mailbox.add(raw)
    channels.poll_mailboxes(db, force=True)
    events.run_due_actions(db)


def _conversation(db: Session, handle: str = CUSTOMER) -> Conversation:
    found = db.scalar(select(Conversation).where(Conversation.customer_handle == handle))
    assert found is not None
    return found


# ------------------------------------------------------------------ parsing


def test_parsing_keeps_text_threading_and_lists_attachments() -> None:
    msg = EmailMessage()
    msg["From"] = "=?utf-8?q?Fran=C3=A7oise?= <francoise@example.com>"
    msg["To"] = USER
    msg["Subject"] = "=?utf-8?q?R=C3=A9servation?="
    msg["Message-ID"] = "<abc@example.com>"
    msg["In-Reply-To"] = "<prev@mixt.example>"
    msg["References"] = "<first@mixt.example> <prev@mixt.example>"
    msg["Authentication-Results"] = "mx.mixt.example; spf=pass smtp.mailfrom=example.com; dkim=pass; dmarc=pass"
    msg.set_content("Plain text part")
    msg.add_alternative("<p>HTML <b>part</b></p>", subtype="html")
    msg.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="report.pdf")
    parsed = email_channel.parse(bytes(msg))
    assert parsed["from_name"] == "Françoise" and parsed["from_address"] == "francoise@example.com"
    assert parsed["subject"] == "Réservation" and parsed["text"] == "Plain text part"
    assert parsed["in_reply_to"] == "<prev@mixt.example>"
    assert parsed["references"] == ["<first@mixt.example>", "<prev@mixt.example>"]
    assert parsed["attachments"] == [
        {"filename": "report.pdf", "content_type": "application/pdf", "size": 13, "stored": False}
    ]
    assert parsed["authentication"] == {"dmarc": "pass", "spf": "pass", "dkim": "pass"}
    assert parsed["auto_reply"] is False and parsed["dsn"] is None


def test_html_only_mail_becomes_plain_text_and_scripts_are_dropped() -> None:
    raw = _email(
        html="<html><head><style>p{}</style><script>alert(1)</script></head><body><p>Hi&nbsp;there</p>"
        "<p>Line&amp;two<br>three</p></body></html>"
    )
    text = email_channel.parse(raw)["text"]
    assert "alert" not in text and "<" not in text
    assert text.splitlines() == ["Hi there", "", "Line&two", "three"]
    no_id = email_channel.parse(b"From: a@example.com\r\nSubject: x\r\n\r\nbody")
    assert no_id["message_id"].endswith("@mixt.invalid>")  # still stored once


def test_auto_replies_and_delivery_reports_are_recognised() -> None:
    assert email_channel.parse(_email(headers={"Auto-Submitted": "auto-replied"}))["auto_reply"] is True
    dsn = _bounce("<sent-1@mixt.example>", CUSTOMER, "5.1.1")
    report = email_channel.parse(dsn)["dsn"]
    assert report == {
        "status": "5.1.1",
        "action": "failed",
        "recipient": CUSTOMER,
        "original_message_id": "<sent-1@mixt.example>",
    }
    assert email_channel.reply_subject("Re: Hello", "x") == "Re: Hello"
    assert email_channel.reply_subject("", "Your message") == "Re: Your message"
    assert email_channel.strip_reply_prefix("RE: Fwd: re: Trial") == "Trial"


def _bounce(original_id: str, recipient: str, status: str) -> bytes:
    text = (
        "From: Mail Delivery System <mailer-daemon@mixt.example>\r\n"
        f"To: {USER}\r\n"
        "Subject: Undelivered Mail Returned to Sender\r\n"
        f"Message-ID: {make_msgid(domain='mixt.example')}\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="BOUNDARY"\r\n'
        "\r\n"
        "--BOUNDARY\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "Your message could not be delivered.\r\n"
        "--BOUNDARY\r\n"
        "Content-Type: message/delivery-status\r\n\r\n"
        "Reporting-MTA: dns; mx.mixt.example\r\n\r\n"
        f"Final-Recipient: rfc822; {recipient}\r\n"
        "Action: failed\r\n"
        f"Status: {status}\r\n\r\n"
        "--BOUNDARY\r\n"
        "Content-Type: text/rfc822-headers\r\n\r\n"
        f"Message-ID: {original_id}\r\n"
        f"To: {recipient}\r\n"
        "Subject: Re: IGCSE Physics tutoring\r\n\r\n"
        "--BOUNDARY--\r\n"
    )
    return text.encode()


# ------------------------------------------------------------------ connecting and reading


def test_connect_validates_and_keeps_the_password_secret(
    db: Session, client: TestClient, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    admin = people["admin"]
    bad = _setup(imap, smtp.port)
    bad.imap_security = "plain"
    with pytest.raises(ValidationFailed, match="encrypted"):
        channels.connect_mailbox(db, admin.actor, _a(db, admin), bad)
    bad.imap_security, bad.smtp_host = "ssl", "bad host!"
    with pytest.raises(ValidationFailed, match="server name"):
        channels.connect_mailbox(db, admin.actor, _a(db, admin), bad)
    api = sign_in(client, db, admin)
    created = api.post(
        "/api/v1/integrations/mailbox",
        json={
            "display_name": "Mixt Sales",
            "address": USER,
            "username": USER,
            "password": PASSWORD,
            "imap_host": "127.0.0.1",
            "imap_port": imap.port,
            "imap_security": "none",
            "smtp_host": "127.0.0.1",
            "smtp_port": smtp.port,
            "smtp_security": "none",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert PASSWORD not in created.text and body["provider"] == "imap_smtp"
    assert [c["kind"] for c in body["credentials"]] == ["password"]
    assert body["channel_account"]["address"] == USER and body["channel_account"]["enabled"] is False
    check = api.post(f"/api/v1/integrations/{body['id']}/check").json()
    assert check == {
        "ok": True,
        "code": None,
        "detail": "Connected: signed in to IMAP and SMTP.",
        "verified_name": None,
        "quality_rating": None,
        "display_phone_number": None,
        "number_matches": None,
    }
    with pytest.raises(Exception, match="already connected"):
        channels.connect_mailbox(db, admin.actor, _a(db, admin), _setup(imap, smtp.port))


def test_production_refuses_unencrypted_mail_connections(
    db: Session, imap: FakeImap, people: dict[str, TestUser], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Staging:
        class env:  # noqa: N801
            value = "staging"

    monkeypatch.setattr(channels, "get_config", lambda: Staging)
    with pytest.raises(ValidationFailed, match="encrypted"):
        channels.connect_mailbox(db, people["admin"].actor, _a(db, people["admin"]), _setup(imap, 25))


def test_first_check_starts_from_now_then_new_mail_arrives_once(
    db: Session, client: TestClient, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    imap.mailbox.add(_email(body="An old message from last year", sender="old@example.com"))
    connected = _connect(db, people["admin"], imap, smtp.port)
    first = channels.poll_mailboxes(db, force=True)
    assert first.mailboxes == 1 and first.stored == 0  # old mail is never imported
    assert connected.channel_account.sync_state["last_uid"] == 1
    rep = people["rep"]
    account = crm.create_account(db, rep.actor, _a(db, rep), "Khan family", country_of_residence="QA")
    contact = crm.add_contact(db, rep.actor, _a(db, rep), account.id, {"role": "guardian", "first_name": "Aisha"})
    crm.add_contact_point(db, rep.actor, _a(db, rep), contact.id, "email", CUSTOMER)
    raw = _email()
    _receive(db, imap, raw)
    conversation = _conversation(db)
    assert conversation.account_id == account.id and conversation.contact_id == contact.id
    assert conversation.subject == "IGCSE Physics tutoring" and conversation.unread_count == 1
    assert conversation.assigned_user_id == rep.id and conversation.service_window_expires_at is None
    message = db.scalar(select(Message).where(Message.direction == "inbound"))
    assert message is not None and message.content_type == "email"
    assert message.body_text == "Hello, do you offer IGCSE Physics?" and message.email_meta is not None
    assert message.email_meta["subject"] == "IGCSE Physics tutoring"
    assert all(c.split()[0] in ("CAPABILITY", "LOGIN", "EXAMINE", "UID", "LOGOUT") for c in imap.mailbox.commands)
    assert not any("STORE" in c or "EXPUNGE" in c for c in imap.mailbox.commands)  # read-only
    # The mailbox is rebuilt (new UIDVALIDITY): recent mail is read again but stored only once.
    imap.mailbox.uidvalidity += 1
    again = channels.poll_mailboxes(db, force=True)
    assert again.stored == 0 and len(list(db.scalars(select(Message).where(Message.direction == "inbound")))) == 1
    # Not due yet: the worker leaves the mailbox alone until the interval has passed.
    assert channels.poll_mailboxes(db).mailboxes == 0
    api = sign_in(client, db, rep)
    listed = api.get("/api/v1/inbox/conversations").json()
    assert listed[0]["channel"] == "email" and listed[0]["subject"] == "IGCSE Physics tutoring"
    assert listed[0]["reply_allowed"] is True and listed[0]["window_open"] is False


def test_reply_is_sent_in_the_customers_thread(
    db: Session, client: TestClient, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    _connect(db, people["admin"], imap, smtp.port)
    channels.poll_mailboxes(db, force=True)
    original = make_msgid(domain="example.com")
    _receive(db, imap, _email(message_id=original, headers={"References": "<older@example.com>"}))
    conversation = _conversation(db)
    manager = sign_in(client, db, people["manager"])
    sent = manager.post(
        f"/api/v1/inbox/conversations/{conversation.id}/messages",
        json={"text": "Hello Aisha,\n\nYes, we do. When would suit you for a free trial?"},
        headers={"Idempotency-Key": "email-reply-1"},
    )
    assert sent.status_code == 202, sent.text
    out = sent.json()
    assert out["content_type"] == "email" and out["email"]["subject"] == "Re: IGCSE Physics tutoring"
    assert templates_empty(db, people["manager"], conversation.id)
    assert events.run_due_actions(db).done == 1
    [envelope] = smtp.handler.received
    assert envelope.rcpt_tos == [CUSTOMER]
    delivered = message_from_bytes(envelope.original_content or b"", policy=policy.default)
    assert delivered["From"] == f"Mixt Sales <{USER}>" and delivered["To"] == f"Aisha Khan <{CUSTOMER}>"
    assert delivered["Subject"] == "Re: IGCSE Physics tutoring"
    assert delivered["In-Reply-To"] == original
    assert delivered["References"] == f"<older@example.com> {original}"
    assert delivered["Message-ID"].endswith("@mixt.example>")
    row = db.get(Message, uuid.UUID(out["id"]))
    assert row is not None and row.status == "sent" and row.sent_at is not None
    assert row.provider_message_id == delivered["Message-ID"]
    # A bounce for that message marks it failed and blocks the address.
    _receive(db, imap, _bounce(row.provider_message_id or "", CUSTOMER, "5.1.1"))
    db.refresh(row)
    assert row.status == "failed" and row.failure_code == "BOUNCED"
    entry = db.scalar(select(SuppressionEntry).where(SuppressionEntry.value == CUSTOMER))
    assert entry is not None and entry.kind == "email" and entry.reason == "bounce"
    blocked = manager.post(f"/api/v1/inbox/conversations/{conversation.id}/messages", json={"text": "Hello again"})
    assert blocked.json()["code"] == "RECIPIENT_SUPPRESSED"


def templates_empty(db: Session, user: TestUser, conversation_id: uuid.UUID) -> bool:
    if messaging.templates_for(db, _a(db, user), conversation_id) != []:
        return False
    with pytest.raises(ValidationFailed, match="Templates are for WhatsApp"):
        messaging.send_template(db, user.actor, _a(db, user), conversation_id, uuid.uuid4(), [], None)
    return True


def test_email_channel_is_off_until_switched_on(
    db: Session, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    admin, manager = people["admin"], people["manager"]
    _connect(db, admin, imap, smtp.port, enable=False)
    channels.poll_mailboxes(db, force=True)
    _receive(db, imap, _email())
    conversation = _conversation(db)  # received mail is stored even while sending is off
    with pytest.raises(ValidationFailed) as off:
        messaging.send_text(db, manager.actor, _a(db, manager), conversation.id, "Hi", None)
    assert off.value.code == "CHANNEL_OFF"
    settings.change(db, admin.actor, _a(db, admin), "channels.email.mailboxes", [USER], "safe_default", None)
    with pytest.raises(ValidationFailed):  # the provider setting is still unset
        messaging.send_text(db, manager.actor, _a(db, manager), conversation.id, "Hi", None)
    settings.change(db, admin.actor, _a(db, admin), "channels.email.provider", "imap_smtp", "safe_default", None)
    assert messaging.send_text(db, manager.actor, _a(db, manager), conversation.id, "Hi", None).message.status == (
        "queued"
    )


def test_auto_replies_forged_senders_and_unsubscribe(
    db: Session, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    _connect(db, people["admin"], imap, smtp.port)
    channels.poll_mailboxes(db, force=True)
    rep = people["rep"]
    account = crm.create_account(db, rep.actor, _a(db, rep), "Khan family", country_of_residence="QA")
    contact = crm.add_contact(db, rep.actor, _a(db, rep), account.id, {"role": "guardian", "first_name": "Aisha"})
    crm.add_contact_point(db, rep.actor, _a(db, rep), contact.id, "email", CUSTOMER)
    # A message that fails DMARC is not linked to the household that owns the address.
    _receive(db, imap, _email(headers={"Authentication-Results": "mx.mixt.example; dmarc=fail"}))
    conversation = _conversation(db)
    assert conversation.account_id is None
    message = db.scalar(select(Message).where(Message.conversation_id == conversation.id))
    assert message is not None and (message.email_meta or {})["authentication"] == {"dmarc": "fail"}
    # Out-of-office replies are kept, but do not count as unread.
    unread = conversation.unread_count
    _receive(db, imap, _email(subject="Automatic reply: Away", headers={"Auto-Submitted": "auto-replied"}))
    db.refresh(conversation)
    assert conversation.unread_count == unread
    # "Unsubscribe" as the subject blocks the address and withdraws email marketing consent.
    manager = people["manager"]
    messaging.link_customer(db, manager.actor, _a(db, manager), conversation.id, account.id, contact.id, False)
    crm.record_consent(
        db,
        rep.actor,
        _a(db, rep),
        contact.id,
        "marketing_email",
        "granted",
        "consent",
        "staff_logged",
        {"note": "Asked for the newsletter"},
    )
    _receive(db, imap, _email(subject="Unsubscribe", body="Please remove me"))
    assert messaging.is_suppressed(db, "email", CUSTOMER)
    assert crm.latest_consent_status(db, contact.id, "marketing_email") == "withdrawn"
    entry = db.scalar(select(SuppressionEntry).where(SuppressionEntry.value == CUSTOMER))
    assert entry is not None and entry.source == "email_reply" and entry.reason == "opt_out"
    # Our own copies in the mailbox are ignored.
    _receive(db, imap, _email(sender=f"Mixt Sales <{USER}>", subject="Copy"))
    assert db.scalar(select(Conversation).where(Conversation.customer_handle == USER)) is None


def test_send_failures(db: Session, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]) -> None:
    connected = _connect(db, people["admin"], imap, smtp.port)
    channels.poll_mailboxes(db, force=True)
    _receive(db, imap, _email())
    conversation = _conversation(db)
    manager = people["manager"]

    def reply() -> Message:
        return messaging.send_text(db, manager.actor, _a(db, manager), conversation.id, "Hello", None).message

    # The server is busy (4xx): retried later.
    smtp.handler.temporary_failure = True
    busy = reply()
    events.run_due_actions(db)
    db.refresh(busy)
    action = db.scalar(select(ScheduledAction).where(ScheduledAction.dedupe_key == f"send:{busy.id}"))
    assert busy.status == "queued" and action is not None and action.status == "pending"
    smtp.handler.temporary_failure = False
    # The address does not exist (550): failed, not retried.
    smtp.handler.refuse.add(CUSTOMER)
    events.run_due_actions(db, now=now_utc().replace(year=now_utc().year + 1))
    db.refresh(busy)
    assert busy.status == "failed" and busy.failure_code == "RECIPIENT_REFUSED"
    smtp.handler.refuse.clear()
    # A wrong password puts the mailbox in error and stops further sends.
    connection_id = connected.view.connection.id
    integrations.set_credential(db, people["admin"].actor, _a(db, people["admin"]), connection_id, "password", "wrong")
    denied = reply()
    events.run_due_actions(db)
    db.refresh(denied)
    assert denied.status == "failed" and denied.failure_code == "AUTH_FAILED"
    assert integrations.get_connection(db, connection_id).status == "error"
    with pytest.raises(ValidationFailed) as unavailable:
        reply()
    assert unavailable.value.code == "CHANNEL_UNAVAILABLE"


def test_reading_problems_are_reported(
    db: Session, client: TestClient, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    connected = _connect(db, people["admin"], imap, smtp.port)
    connection_id = connected.view.connection.id
    imap.mailbox.password = "changed-at-the-provider"
    result = channels.poll_mailboxes(db, force=True)
    assert result.failed == 1
    connection = integrations.get_connection(db, connection_id)
    assert connection.status == "error" and "AUTH_FAILED" in (connection.last_error or "")
    api = sign_in(client, db, people["admin"])
    check = api.post(f"/api/v1/integrations/{connection_id}/check").json()
    assert check["ok"] is False and check["code"] == "AUTH_FAILED"
    imap.mailbox.password = PASSWORD
    assert api.post(f"/api/v1/integrations/{connection_id}/check").json()["ok"] is True
    polled = api.post(f"/api/v1/integrations/{connection_id}/poll").json()
    assert polled == {"mailboxes": 1, "stored": 0, "failed": 0}
    out = api.get(f"/api/v1/integrations/{connection_id}").json()
    assert out["channel_account"]["last_check_error"] is None and out["channel_account"]["last_checked_at"]
    # An unreachable server is a temporary problem: the mailbox stays connected.
    imap.stop()
    assert channels.poll_mailboxes(db, force=True).failed == 1
    assert integrations.get_connection(db, connection_id).status == "connected"


def test_lead_from_an_email_conversation(
    db: Session, client: TestClient, imap: FakeImap, smtp: FakeSmtp, people: dict[str, TestUser]
) -> None:
    _connect(db, people["admin"], imap, smtp.port)
    channels.poll_mailboxes(db, force=True)
    _receive(db, imap, _email(sender="Omar Saleh <omar.saleh@example.com>", body="Year 9 maths please"))
    conversation = _conversation(db, "omar.saleh@example.com")
    manager = sign_in(client, db, people["manager"])
    created = manager.post(f"/api/v1/inbox/conversations/{conversation.id}/lead", json={"country": "QA"})
    assert created.status_code == 201, created.text
    lead = db.get(Lead, uuid.UUID(created.json()["lead_id"]))
    assert lead is not None and lead.submitted_email == "omar.saleh@example.com" and lead.submitted_phone is None
    assert lead.submitted_name == "Omar Saleh" and lead.submitted_message == "Year 9 maths please"
    assert crm.accounts_matching_contact_points(db, [("email", "omar.saleh@example.com")]) == [lead.account_id]
