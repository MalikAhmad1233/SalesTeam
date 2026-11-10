"""Applies the configured rate limits (``mixt.core.ratelimit``) and turns refusals into 429s."""

from __future__ import annotations

from mixt.core.config import get_config
from mixt.core.errors import RateLimited
from mixt.core.logging import get_logger
from mixt.core.ratelimit import Decision, limiter_for

log = get_logger("mixt.throttle")

MESSAGES = {
    "login_per_ip": "Too many sign-in attempts from this network. Wait a few minutes and try again.",
    "login_per_account": "Too many sign-in attempts for this account. Wait a few minutes and try again.",
    "mfa_per_session": "Too many verification attempts. Wait a few minutes and try again.",
    "password_per_user": "Too many password change attempts. Wait a few minutes and try again.",
    "sso_per_ip": "Too many single sign-on attempts. Wait a few minutes and try again.",
    "import_per_user": "Too many imports in a short time. Wait a while and try again.",
    "api_per_user": "Too many requests. Slow down and try again shortly.",
    "api_per_ip": "Too many requests. Slow down and try again shortly.",
    "enquiry_per_ip": "Too many enquiries from this network. Please wait a few minutes and try again.",
    "webhook_per_connection": "Too many webhook deliveries.",
}


def check(name: str, identity: str | None) -> Decision:
    config = get_config()
    if not identity:
        return Decision(True, 0, 0)
    return limiter_for(config).hit(name, identity, config.rate(name))


def enforce(name: str, identity: str | None) -> None:
    decision = check(name, identity)
    if not decision.allowed:
        log.warning("rate_limited", limit=name, retry_after=decision.retry_after_seconds)
        raise RateLimited("RATE_LIMITED", MESSAGES[name], decision.retry_after_seconds, limit=name)
