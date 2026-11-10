"""WhatsApp Business Cloud API adapter (docs/07 §2).

Pure protocol code: signature checks, webhook parsing, Graph API calls and error mapping. The
rules (customer-service window, templates, consent, opt-outs) live in ``messaging.service``.

The Graph API version is part of each connection's configuration and is never assumed here:
Meta retires versions on a schedule, so the admin sets the version Mixt's app is approved for.
Error codes follow Meta's published WhatsApp Cloud API error list; they are re-checked against
the live sandbox when Mixt's account is connected (docs/07 note at the top).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

GRAPH_BASE_URL = "https://graph.facebook.com"
TIMEOUT_SECONDS = 10.0
VERSION_RE = re.compile(r"^v\d{1,3}\.\d{1,2}$")
ID_RE = re.compile(r"^\d{5,32}$")
MAX_TEXT_LENGTH = 4096
MAX_TEMPLATE_PAGES = 20

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Route Graph API calls through ``transport`` (tests use a fake Graph API)."""
    global _transport  # noqa: PLW0603
    _transport = transport


def _client() -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=TIMEOUT_SECONDS, follow_redirects=False)


# ------------------------------------------------------------------ webhook authenticity


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Check ``X-Hub-Signature-256: sha256=<hex>``, the HMAC-SHA256 of the raw body with the app secret."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256=").strip().lower())


def sign(app_secret: str, raw_body: bytes) -> str:
    """The header value Meta would send (used by tests and the local webhook simulator)."""
    return "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_subscription(mode: str | None, token: str | None, expected_token: str) -> bool:
    return mode == "subscribe" and token is not None and hmac.compare_digest(token, expected_token)


def event_id(raw_body: bytes) -> str:
    """Meta sends no event id, so a delivery is identified by the hash of its exact body."""
    return "sha256:" + hashlib.sha256(raw_body).hexdigest()


# ------------------------------------------------------------------ webhook parsing


@dataclass(frozen=True)
class InboundMessage:
    phone_number_id: str
    wa_id: str
    profile_name: str | None
    message_id: str
    timestamp: datetime
    content_type: str  # text | interactive | media
    text: str | None
    media: dict[str, Any] | None


@dataclass(frozen=True)
class StatusUpdate:
    phone_number_id: str
    message_id: str
    status: str
    timestamp: datetime
    recipient: str | None
    error_code: int | None
    error_title: str | None


@dataclass(frozen=True)
class TemplateUpdate:
    template_id: str
    name: str | None
    language: str | None
    event: str
    reason: str | None


@dataclass
class ParsedWebhook:
    messages: list[InboundMessage] = field(default_factory=list)
    statuses: list[StatusUpdate] = field(default_factory=list)
    templates: list[TemplateUpdate] = field(default_factory=list)
    other_fields: list[str] = field(default_factory=list)


def _ts(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)


_MEDIA_TYPES = ("image", "video", "audio", "document", "sticker")


def _content(msg: dict[str, Any]) -> tuple[str, str | None, dict[str, Any] | None] | None:
    kind = msg.get("type")
    if kind == "text":
        return "text", str((msg.get("text") or {}).get("body") or ""), None
    if kind == "button":
        return "interactive", str((msg.get("button") or {}).get("text") or ""), None
    if kind == "interactive":
        inner = msg.get("interactive") or {}
        reply = inner.get("button_reply") or inner.get("list_reply") or {}
        return "interactive", str(reply.get("title") or ""), None
    if kind in _MEDIA_TYPES:
        body = msg.get(kind) or {}
        media = {
            "type": kind,
            "provider_media_id": body.get("id"),
            "mime_type": body.get("mime_type"),
            "sha256": body.get("sha256"),
            "filename": body.get("filename"),
            "stored": False,  # downloading to private storage arrives with object storage (Phase 3b)
        }
        return "media", body.get("caption"), {k: v for k, v in media.items() if v is not None}
    if kind == "location":
        loc = msg.get("location") or {}
        media = {k: loc.get(k) for k in ("latitude", "longitude", "name", "address") if loc.get(k) is not None}
        return "media", None, {"type": "location", **media}
    if kind == "contacts":
        return "media", None, {"type": "contacts", "count": len(msg.get("contacts") or [])}
    if kind == "reaction":
        return None  # reactions are not stored as messages
    return "media", None, {"type": "unsupported", "provider_type": str(kind)}


def parse_webhook(payload: dict[str, Any]) -> ParsedWebhook:
    parsed = ParsedWebhook()
    if payload.get("object") != "whatsapp_business_account":
        parsed.other_fields.append(str(payload.get("object")))
        return parsed
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            field_name = change.get("field")
            value = change.get("value") or {}
            if field_name == "messages":
                phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
                names = {str(c.get("wa_id")): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
                for msg in value.get("messages") or []:
                    content = _content(msg)
                    if content is None or not msg.get("id") or not msg.get("from"):
                        continue
                    content_type, text, media = content
                    wa_id = str(msg["from"])
                    parsed.messages.append(
                        InboundMessage(
                            phone_number_id,
                            wa_id,
                            names.get(wa_id),
                            str(msg["id"]),
                            _ts(msg.get("timestamp")),
                            content_type,
                            text,
                            media,
                        )
                    )
                for status in value.get("statuses") or []:
                    errors = status.get("errors") or [{}]
                    code = errors[0].get("code")
                    parsed.statuses.append(
                        StatusUpdate(
                            phone_number_id,
                            str(status.get("id")),
                            str(status.get("status")),
                            _ts(status.get("timestamp")),
                            status.get("recipient_id"),
                            int(code) if isinstance(code, int | str) and str(code).isdigit() else None,
                            errors[0].get("title") or errors[0].get("message"),
                        )
                    )
            elif field_name == "message_template_status_update":
                parsed.templates.append(
                    TemplateUpdate(
                        str(value.get("message_template_id")),
                        value.get("message_template_name"),
                        value.get("message_template_language"),
                        str(value.get("event") or ""),
                        value.get("reason"),
                    )
                )
            else:
                parsed.other_fields.append(str(field_name))
    return parsed


# ------------------------------------------------------------------ errors


@dataclass(frozen=True)
class ErrorKind:
    code: str
    retryable: bool
    connection_problem: bool = False  # the connection itself needs an admin (token, permissions, account)


_RATE_LIMITED = ErrorKind("RATE_LIMITED", True)
_TEMPLATE = ErrorKind("TEMPLATE_PROBLEM", False)
_CONNECTION = ErrorKind("CONNECTION_PROBLEM", False, True)
_PROVIDER_CODES: dict[int, ErrorKind] = {
    0: ErrorKind("AUTH_EXCEPTION", False, True),
    1: ErrorKind("PROVIDER_ERROR", True),
    2: ErrorKind("PROVIDER_UNAVAILABLE", True),
    3: _CONNECTION,
    4: _RATE_LIMITED,
    10: _CONNECTION,
    100: ErrorKind("INVALID_REQUEST", False),
    190: ErrorKind("TOKEN_INVALID", False, True),
    368: ErrorKind("ACCOUNT_RESTRICTED", False, True),
    80007: _RATE_LIMITED,
    130429: _RATE_LIMITED,
    131000: ErrorKind("PROVIDER_ERROR", True),
    131005: _CONNECTION,
    131008: ErrorKind("INVALID_REQUEST", False),
    131009: ErrorKind("INVALID_REQUEST", False),
    131016: ErrorKind("PROVIDER_UNAVAILABLE", True),
    131021: ErrorKind("INVALID_RECIPIENT", False),
    131026: ErrorKind("UNDELIVERABLE", False),
    131030: ErrorKind("RECIPIENT_NOT_ALLOWED", False),  # test numbers: recipient not on the allowed list
    131031: ErrorKind("ACCOUNT_RESTRICTED", False, True),
    131042: ErrorKind("PAYMENT_PROBLEM", False, True),
    131045: _CONNECTION,
    131047: ErrorKind("WINDOW_CLOSED", False),
    131049: ErrorKind("NOT_DELIVERED_BY_META", False),
    131050: ErrorKind("MARKETING_STOPPED", False),
    131051: ErrorKind("UNSUPPORTED_MESSAGE", False),
    131052: ErrorKind("MEDIA_ERROR", False),
    131053: ErrorKind("MEDIA_ERROR", False),
    131056: _RATE_LIMITED,
    132000: _TEMPLATE,
    132001: _TEMPLATE,
    132005: _TEMPLATE,
    132007: _TEMPLATE,
    132012: _TEMPLATE,
    132015: _TEMPLATE,
    132016: _TEMPLATE,
    133010: _CONNECTION,
}


def classify(provider_code: int | None, http_status: int | None = None) -> ErrorKind:
    if provider_code is not None and provider_code in _PROVIDER_CODES:
        return _PROVIDER_CODES[provider_code]
    if http_status == 429:
        return _RATE_LIMITED
    if http_status is not None and http_status >= 500:
        return ErrorKind("PROVIDER_UNAVAILABLE", True)
    if http_status in (401, 403):
        return _CONNECTION
    return ErrorKind("PROVIDER_REJECTED", False)


class WhatsAppError(Exception):
    def __init__(
        self,
        kind: ErrorKind,
        detail: str,
        provider_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{kind.code} ({provider_code}): {detail}")
        self.kind = kind
        self.detail = detail
        self.provider_code = provider_code
        self.retry_after = retry_after


# ------------------------------------------------------------------ Graph API


@dataclass(frozen=True)
class GraphConfig:
    version: str
    access_token: str
    base_url: str = GRAPH_BASE_URL


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _call(cfg: GraphConfig, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    if not VERSION_RE.match(cfg.version):
        raise WhatsAppError(_CONNECTION, "The Graph API version in the connection settings is not valid.")
    url = f"{cfg.base_url}/{cfg.version}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {cfg.access_token}"}
    try:
        with _client() as client:
            response = client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise WhatsAppError(ErrorKind("NETWORK_ERROR", True), type(exc).__name__) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        code = error.get("code")
        provider_code = int(code) if isinstance(code, int) else None
        detail = str(error.get("error_user_msg") or error.get("message") or f"HTTP {response.status_code}")
        raise WhatsAppError(
            classify(provider_code, response.status_code), detail[:500], provider_code, _retry_after(response)
        )
    return body if isinstance(body, dict) else {}


def _recipient(e164: str) -> str:
    return e164.lstrip("+")


def _message_id(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    if not messages or not messages[0].get("id"):
        raise WhatsAppError(ErrorKind("PROVIDER_ERROR", True), "The API accepted the call but returned no message id.")
    return str(messages[0]["id"])


def send_text(cfg: GraphConfig, phone_number_id: str, to_e164: str, body: str) -> str:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _recipient(to_e164),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    return _message_id(_call(cfg, "POST", f"{phone_number_id}/messages", json=payload))


def send_template(
    cfg: GraphConfig, phone_number_id: str, to_e164: str, name: str, language: str, variables: list[str]
) -> str:
    template: dict[str, Any] = {"name": name, "language": {"code": language}}
    if variables:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": value} for value in variables]}
        ]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _recipient(to_e164),
        "type": "template",
        "template": template,
    }
    return _message_id(_call(cfg, "POST", f"{phone_number_id}/messages", json=payload))


def phone_number_info(cfg: GraphConfig, phone_number_id: str) -> dict[str, Any]:
    return _call(
        cfg,
        "GET",
        phone_number_id,
        params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
    )


def fetch_templates(cfg: GraphConfig, waba_id: str) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    params: dict[str, Any] | None = {"fields": "id,name,language,status,category,components", "limit": 100}
    path = f"{waba_id}/message_templates"
    for _ in range(MAX_TEMPLATE_PAGES):
        body = _call(cfg, "GET", path, params=params)
        templates.extend(t for t in body.get("data") or [] if isinstance(t, dict))
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (body.get("paging") or {}).get("next"):
            break
        params = {"fields": "id,name,language,status,category,components", "limit": 100, "after": after}
    return templates


# ------------------------------------------------------------------ templates

_POSITIONAL = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_NAMED = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PROVIDER_TEMPLATE_STATUS = {
    "APPROVED": "approved",
    "PENDING": "pending",
    "IN_APPEAL": "pending",
    "REJECTED": "rejected",
    "PAUSED": "paused",
    "DISABLED": "disabled",
    "PENDING_DELETION": "disabled",
    "DELETED": "disabled",
    "ARCHIVED": "disabled",
    "LIMIT_EXCEEDED": "disabled",
    "FLAGGED": "approved",  # still sendable; Meta may pause it if quality stays low
    "REINSTATED": "approved",
}


@dataclass(frozen=True)
class TemplateFacts:
    body: str
    variable_count: int
    unsupported_reason: str | None


def template_facts(category: str, components: list[dict[str, Any]]) -> TemplateFacts:
    """Body text, number of body variables, and why Mixt cannot fill the template yet (if so)."""
    body = ""
    reasons: list[str] = []
    for component in components:
        kind = str(component.get("type") or "").upper()
        text = str(component.get("text") or "")
        if kind == "BODY":
            body = text
        elif kind == "HEADER":
            if str(component.get("format") or "TEXT").upper() != "TEXT":
                reasons.append("it has a media or location header")
            elif _POSITIONAL.search(text) or _NAMED.search(text):
                reasons.append("its header has variables")
        elif kind == "BUTTONS":
            for button in component.get("buttons") or []:
                if str(button.get("type") or "").upper() == "URL" and "{{" in str(button.get("url") or ""):
                    reasons.append("a button has a variable link")
                elif str(button.get("type") or "").upper() in ("OTP", "COPY_CODE", "FLOW", "CATALOG", "MPM"):
                    reasons.append(f"it has a {str(button.get('type')).lower()} button")
    if category == "authentication":
        reasons.append("authentication templates are not used by Mixt")
    numbers = sorted({int(n) for n in _POSITIONAL.findall(body)})
    if _NAMED.search(body):
        reasons.append("it uses named variables")
    elif numbers and numbers != list(range(1, len(numbers) + 1)):
        reasons.append("its variables are not numbered 1, 2, 3...")
    return TemplateFacts(body, len(numbers), "; ".join(dict.fromkeys(reasons)) or None)


def render_template(body: str, variables: list[str]) -> str:
    return _POSITIONAL.sub(lambda m: variables[int(m.group(1)) - 1], body)
