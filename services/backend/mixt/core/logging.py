"""Structured JSON logging with a correlation id and personal-data redaction.

Message bodies, emails, phone numbers, passwords, tokens and secrets must never reach logs in
clear text. Redaction is applied to every event as a last line of defence.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = re.compile(
    r"(password|passcode|secret|token|authorization|cookie|otp|code|email|phone|body|message_text)", re.I
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
REDACTED = "[redacted]"


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _PHONE_RE.sub(REDACTED, _EMAIL_RE.sub(REDACTED, value))
    if isinstance(value, dict):
        return {k: (REDACTED if _SENSITIVE_KEYS.search(str(k)) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key in ("event", "level", "timestamp", "logger", "correlation_id"):
            if key == "event":
                event_dict[key] = redact_value(event_dict[key])
            continue
        if _SENSITIVE_KEYS.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    renderer: Any = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
