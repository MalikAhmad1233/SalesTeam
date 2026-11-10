"""TOTP (RFC 6238) with replay protection: a code's time step can only be used once."""

from __future__ import annotations

import hmac
import time

import pyotp

ISSUER = "Mixt AI"
_STEP_SECONDS = 30
_WINDOW = 1  # accept one step of clock drift either side


def new_secret() -> str:
    return str(pyotp.random_base32())


def provisioning_uri(secret: str, email: str) -> str:
    return str(pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER))


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // _STEP_SECONDS)


def code_for_step(secret: str, step: int) -> str:
    return str(pyotp.TOTP(secret).generate_otp(step))


def verify(secret: str, code: str, last_used_step: int | None, now: float | None = None) -> int | None:
    """Return the matching time step, or None. Steps at or before ``last_used_step`` are rejected."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    base = current_step(now)
    for step in range(base - _WINDOW, base + _WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(code_for_step(secret, step), code):
            return step
    return None
