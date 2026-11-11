"""Email over IMAP (read) and SMTP (send): provider-neutral, because Mixt uses neither Google
Workspace nor Microsoft 365 (BD-034; docs/07 §3).

Pure protocol code: connecting with TLS, reading new messages read-only by UID, parsing MIME
(text, threading headers, attachments listed, delivery-status reports, auto-replies, the
authentication results added by Mixt's mail service), composing replies and sending them.
The rules (suppression, consent, matching to households) live in ``messaging.service``.
"""

from __future__ import annotations

import contextlib
import hashlib
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.parser import BytesParser, HeaderParser
from email.utils import formataddr, formatdate, make_msgid, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

TIMEOUT_SECONDS = 20.0
MAX_TEXT_CHARS = 100_000
MAX_FETCH = 50
MAX_ATTACHMENTS_LISTED = 20
RESYNC_DAYS = 2
SECURITY_MODES = ("ssl", "starttls", "none")  # "none" is for local tests only (refused when deployed)


@dataclass(frozen=True)
class MailboxConfig:
    address: str
    display_name: str
    username: str
    password: str
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str


@dataclass(frozen=True)
class MailErrorKind:
    code: str
    retryable: bool
    connection_problem: bool = False


class MailError(Exception):
    def __init__(self, kind: MailErrorKind, detail: str) -> None:
        super().__init__(f"{kind.code}: {detail}")
        self.kind = kind
        self.detail = detail


_NETWORK = MailErrorKind("NETWORK_ERROR", True)
_AUTH = MailErrorKind("AUTH_FAILED", False, True)
_TLS = MailErrorKind("TLS_ERROR", False, True)
_PROTOCOL = MailErrorKind("MAIL_SERVER_ERROR", True)


def _context() -> ssl.SSLContext:
    return ssl.create_default_context()  # certificate and host name checked


# ------------------------------------------------------------------ IMAP


@dataclass(frozen=True)
class FetchResult:
    uidvalidity: int
    last_uid: int
    messages: list[tuple[int, bytes]]
    resynced: bool = False  # the mailbox was rebuilt; recent mail was read again


def _imap(cfg: MailboxConfig) -> imaplib.IMAP4:
    try:
        if cfg.imap_security == "ssl":
            conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                cfg.imap_host, cfg.imap_port, ssl_context=_context(), timeout=TIMEOUT_SECONDS
            )
        else:
            conn = imaplib.IMAP4(cfg.imap_host, cfg.imap_port, timeout=TIMEOUT_SECONDS)
            if cfg.imap_security == "starttls":
                conn.starttls(ssl_context=_context())
    except ssl.SSLError as exc:
        raise MailError(_TLS, f"Secure connection to the mail server failed ({exc.reason}).") from exc
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(_NETWORK, f"Could not reach the IMAP server ({type(exc).__name__}).") from exc
    try:
        conn.login(cfg.username, cfg.password)
    except imaplib.IMAP4.error as exc:
        _close(conn)
        raise MailError(_AUTH, "The mail server refused the user name or password.") from exc
    return conn


def _close(conn: imaplib.IMAP4) -> None:
    with contextlib.suppress(OSError, imaplib.IMAP4.error):
        conn.logout()


def _untagged_int(conn: imaplib.IMAP4, name: str) -> int | None:
    _, data = conn.response(name)
    if not data or data[0] is None:
        return None
    match = re.search(rb"\d+", data[0] if isinstance(data[0], bytes) else str(data[0]).encode())
    return int(match.group()) if match else None


def _uids(data: list[Any]) -> list[int]:
    raw = data[0] if data and data[0] else b""
    return sorted({int(x) for x in (raw.split() if isinstance(raw, bytes) else [])})


def fetch_new(cfg: MailboxConfig, state: dict[str, Any] | None, limit: int = MAX_FETCH) -> FetchResult:
    """New messages since the last check, read-only (nothing is marked read, moved or deleted).

    The first check only records where the mailbox is now, so old mail is never imported. When
    the mailbox's UIDVALIDITY changes, the last two days are read again (duplicates are dropped
    later by Message-ID).
    """
    conn = _imap(cfg)
    try:
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise MailError(_PROTOCOL, "The mailbox's INBOX could not be opened.")
        uidvalidity = _untagged_int(conn, "UIDVALIDITY") or 0
        uidnext = _untagged_int(conn, "UIDNEXT")
        if state is None or "last_uid" not in state:
            if uidnext is None:
                _, data = conn.uid("SEARCH", "ALL")
                found = _uids(data)
                uidnext = (found[-1] + 1) if found else 1
            return FetchResult(uidvalidity, uidnext - 1, [])
        last = int(state["last_uid"])
        resynced = int(state.get("uidvalidity") or 0) != uidvalidity
        if resynced:
            since = (datetime.now(tz=UTC) - timedelta(days=RESYNC_DAYS)).strftime("%d-%b-%Y")
            _, data = conn.uid("SEARCH", "SINCE", since)
            candidates = _uids(data)
            last = 0
        else:
            _, data = conn.uid("SEARCH", "UID", f"{last + 1}:*")
            candidates = [u for u in _uids(data) if u > last]  # "n:*" always includes the newest message
        chosen = candidates[:limit]
        messages: list[tuple[int, bytes]] = []
        for uid in chosen:
            typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((part[1] for part in data if isinstance(part, tuple) and len(part) > 1), None)
            if typ == "OK" and isinstance(raw, bytes):
                messages.append((uid, raw))
        new_last = chosen[-1] if chosen else max(last, (uidnext - 1) if uidnext else last)
        return FetchResult(uidvalidity, new_last, messages, resynced)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(_NETWORK, f"Reading the mailbox failed ({type(exc).__name__}).") from exc
    finally:
        _close(conn)


def check(cfg: MailboxConfig) -> None:
    """Sign in to IMAP and SMTP without reading or sending anything. Raises ``MailError``."""
    conn = _imap(cfg)
    try:
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise MailError(_PROTOCOL, "The mailbox's INBOX could not be opened.")
    finally:
        _close(conn)
    with _smtp(cfg):
        pass


# ------------------------------------------------------------------ parsing


class _TextExtractor(HTMLParser):
    _BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"})
    _SKIP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text from HTML (the HTML itself is never stored or rendered)."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    lines = [" ".join(line.split()) for line in "".join(extractor.parts).splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _header(msg: Message, name: str) -> str | None:
    try:
        value = msg.get(name)
    except (ValueError, TypeError, IndexError):
        return None
    return " ".join(str(value).split()) if value is not None else None


def _addresses(msg: Message, name: str) -> list[tuple[str, str]]:
    try:
        header = msg.get(name)
        addresses = getattr(header, "addresses", ()) if header is not None else ()
        return [(a.display_name or "", a.addr_spec) for a in addresses if isinstance(a, Address) and a.addr_spec]
    except (ValueError, TypeError, IndexError):
        return []


def _auto_reply(msg: Message) -> bool:
    auto = (_header(msg, "Auto-Submitted") or "no").lower()
    precedence = (_header(msg, "Precedence") or "").lower()
    return (
        auto != "no"
        or precedence in ("auto_reply", "bulk", "junk", "list")
        or any(_header(msg, h) is not None for h in ("X-Autoreply", "X-Autorespond", "X-Auto-Response-Suppress"))
    )


def _authentication(msg: Message) -> dict[str, str]:
    """Results Mixt's own mail service recorded (the first Authentication-Results header)."""
    value = (_header(msg, "Authentication-Results") or "").lower()
    found: dict[str, str] = {}
    for method in ("dmarc", "spf", "dkim"):
        match = re.search(rf"\b{method}=([a-z]+)", value)
        if match:
            found[method] = match.group(1)
    return found


def _dsn(msg: Message) -> dict[str, Any] | None:
    if msg.get_content_type() != "multipart/report" or str(msg.get_param("report-type") or "").lower() != (
        "delivery-status"
    ):
        return None
    report: dict[str, Any] = {"status": None, "action": None, "recipient": None, "original_message_id": None}
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "message/delivery-status":
            for block in part.get_payload() or []:
                if not isinstance(block, Message):
                    continue
                recipient = block.get("Final-Recipient") or block.get("Original-Recipient")
                if recipient and report["recipient"] is None:
                    report["recipient"] = str(recipient).split(";")[-1].strip()
                if block.get("Status") and report["status"] is None:
                    report["status"] = str(block.get("Status")).strip()
                if block.get("Action") and report["action"] is None:
                    report["action"] = str(block.get("Action")).strip().lower()
        elif kind == "message/rfc822":
            inner = part.get_payload()
            inner_msg = inner[0] if isinstance(inner, list) and inner else inner
            if isinstance(inner_msg, Message):
                report["original_message_id"] = _header(inner_msg, "Message-ID")
        elif kind == "text/rfc822-headers":
            raw_headers = part.get_payload(decode=True)
            text = raw_headers.decode("utf-8", "replace") if isinstance(raw_headers, bytes) else str(raw_headers)
            headers = HeaderParser(policy=policy.default).parsestr(text)
            report["original_message_id"] = report["original_message_id"] or _header(headers, "Message-ID")
    return report


def _text(msg: Message) -> str:
    try:
        body = msg.get_body(preferencelist=("plain", "html")) if isinstance(msg, EmailMessage) else None
        if body is None:
            return ""
        content = str(body.get_content())
        text = html_to_text(content) if body.get_content_type() == "text/html" else content
    except (LookupError, ValueError, TypeError, KeyError):
        return ""
    text = text.replace("\r\n", "\n").strip()
    return text[:MAX_TEXT_CHARS]


def _attachments(msg: Message) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = []
    if not isinstance(msg, EmailMessage):
        return listed
    try:
        for part in msg.iter_attachments():
            payload = part.get_payload(decode=True)
            listed.append(
                {
                    "filename": (part.get_filename() or "attachment")[:200],
                    "content_type": part.get_content_type(),
                    "size": len(payload) if isinstance(payload, bytes) else None,
                    "stored": False,  # downloading to private storage arrives with Phase 3c
                }
            )
            if len(listed) >= MAX_ATTACHMENTS_LISTED:
                break
    except (LookupError, ValueError, TypeError, KeyError):
        pass
    return listed


def _date(msg: Message) -> str | None:
    value = _header(msg, "Date")
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def parse(raw: bytes) -> dict[str, Any]:
    """Everything Mixt keeps from a received email, as JSON (no HTML, no attachment content)."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = _header(msg, "Message-ID") or f"<{hashlib.sha256(raw).hexdigest()}@mixt.invalid>"
    sender = (_addresses(msg, "From") or [("", "")])[0]
    references = (_header(msg, "References") or "").split()
    return {
        "message_id": message_id[:998],
        "from_name": sender[0][:200] or None,
        "from_address": sender[1][:320] or None,
        "to": [a for _, a in _addresses(msg, "To")][:50],
        "cc": [a for _, a in _addresses(msg, "Cc")][:50],
        "subject": (_header(msg, "Subject") or "")[:500],
        "date": _date(msg),
        "in_reply_to": _header(msg, "In-Reply-To"),
        "references": references[-20:],
        "auto_reply": _auto_reply(msg),
        "authentication": _authentication(msg),
        "dsn": _dsn(msg),
        "text": _text(msg),
        "attachments": _attachments(msg),
    }


def event_id(connection_id: str, parsed: dict[str, Any]) -> str:
    """One stored copy per mailbox and Message-ID (the same email can reach two Mixt mailboxes)."""
    digest = hashlib.sha256(str(parsed.get("message_id")).encode("utf-8")).hexdigest()
    return f"{connection_id}:{digest}"


def reply_subject(subject: str | None, fallback: str) -> str:
    base = (subject or "").strip() or fallback
    return base if re.match(r"^(re|aw|sv)\s*:", base, re.IGNORECASE) else f"Re: {base}"


def strip_reply_prefix(subject: str) -> str:
    return re.sub(r"^((re|fw|fwd|aw|sv)\s*:\s*)+", "", subject.strip(), flags=re.IGNORECASE)[:500]


# ------------------------------------------------------------------ sending


def new_message_id(address: str) -> str:
    domain = address.rsplit("@", 1)[-1] if "@" in address else "mixt.invalid"
    return make_msgid(domain=domain)


def compose(
    cfg: MailboxConfig,
    to_address: str,
    to_name: str | None,
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str | None,
    references: list[str],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.display_name, cfg.address))
    msg["To"] = formataddr((to_name or "", to_address))
    msg["Subject"] = subject
    msg["Date"] = formatdate(usegmt=True)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    chain = [*references, *([in_reply_to] if in_reply_to and in_reply_to not in references else [])]
    if chain:
        msg["References"] = " ".join(chain[-20:])
    msg.set_content(body)
    return msg


def _smtp(cfg: MailboxConfig) -> smtplib.SMTP:
    try:
        if cfg.smtp_security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_SECONDS, context=_context()
            )
        else:
            client = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_SECONDS)
            if cfg.smtp_security == "starttls":
                client.starttls(context=_context())
        client.login(cfg.username, cfg.password)
        return client
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(_AUTH, "The mail server refused the user name or password.") from exc
    except ssl.SSLError as exc:
        raise MailError(_TLS, f"Secure connection to the mail server failed ({exc.reason}).") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(_NETWORK, f"Could not reach the SMTP server ({type(exc).__name__}).") from exc


def send(cfg: MailboxConfig, msg: EmailMessage) -> None:
    """Hand the message to Mixt's mail server. Raises ``MailError`` (retryable or not)."""
    client = _smtp(cfg)
    try:
        client.send_message(msg)
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        permanent = all(code >= 500 for code in codes)
        raise MailError(MailErrorKind("RECIPIENT_REFUSED", not permanent), f"Recipient refused ({codes}).") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError(
            MailErrorKind("SENDER_REFUSED", exc.smtp_code < 500, exc.smtp_code >= 500), "Sender refused."
        ) from exc
    except smtplib.SMTPDataError as exc:
        raise MailError(
            MailErrorKind("MESSAGE_REFUSED", exc.smtp_code < 500), f"Message refused ({exc.smtp_code})."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(_NETWORK, f"Sending failed ({type(exc).__name__}).") from exc
    finally:
        with contextlib.suppress(smtplib.SMTPException, OSError):
            client.quit()
