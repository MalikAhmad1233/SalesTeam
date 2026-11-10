"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

import contextlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from mixt.core.errors import ValidationFailed

_hasher = PasswordHasher()  # Argon2id with RFC 9106 low-memory parameters
# Used to keep login timing similar whether or not the email exists.
_DUMMY_HASH = _hasher.hash("mixt-dummy-password-for-timing")

MIN_LENGTH = 12
MAX_LENGTH = 256
_COMMON = frozenset({"password1234", "123456789012", "qwertyuiop12", "mixtacademy1", "letmein12345"})


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if password_hash is None:
        _burn_time(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def _burn_time(password: str) -> None:
    with contextlib.suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        _hasher.verify(_DUMMY_HASH, password)


def burn_time(password: str) -> None:
    """Spend the same time as a real verification (unknown email)."""
    _burn_time(password)


def check_policy(password: str, email: str) -> None:
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"at most {MAX_LENGTH} characters")
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in password.lower():
        problems.append("must not contain your email name")
    if password.lower() in _COMMON or len(set(password)) < 4:
        problems.append("too easy to guess")
    if problems:
        raise ValidationFailed("WEAK_PASSWORD", "Password does not meet the policy: " + "; ".join(problems) + ".")
