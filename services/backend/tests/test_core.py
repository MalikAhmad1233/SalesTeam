"""Core utilities: money, ids, encryption, normalisation, time zones, log redaction."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixt.core import crypto
from mixt.core.config import get_config
from mixt.core.errors import ValidationFailed
from mixt.core.ids import uuid7, uuid7_timestamp_ms
from mixt.core.logging import REDACTED, redact_value
from mixt.core.money import CurrencyMismatch, Money, MoneyError, format_money, parse_major
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.core.timezones import InvalidTimezone, to_local, validate_timezone

# ------------------------------------------------------------------ money


def test_money_requires_integer_minor_units() -> None:
    with pytest.raises(MoneyError):
        Money(10.5, "GBP")  # type: ignore[arg-type]
    with pytest.raises(MoneyError):
        Money(True, "GBP")  # type: ignore[arg-type]
    with pytest.raises(MoneyError):
        Money(100, "gbp")


def test_money_never_combines_currencies() -> None:
    with pytest.raises(CurrencyMismatch):
        _ = Money(100, "USD") + Money(100, "GBP")
    with pytest.raises(CurrencyMismatch):
        _ = Money(100, "AED") < Money(100, "SAR")
    assert Money(28500, "GBP") + Money(1500, "GBP") == Money(30000, "GBP")


def test_parse_major_is_exact() -> None:
    assert parse_major("1,050", "AED", 2) == Money(105000, "AED")
    assert parse_major("1.234", "KWD", 3) == Money(1234, "KWD")
    assert parse_major("3200", "KRW", 0) == Money(3200, "KRW")
    with pytest.raises(MoneyError):
        parse_major("10.005", "GBP", 2)  # would need rounding: refused
    with pytest.raises(MoneyError):
        parse_major("abc", "GBP", 2)
    with pytest.raises(MoneyError):
        parse_major("Infinity", "GBP", 2)


def test_format_always_shows_currency() -> None:
    assert format_money(Money(105000, "AED"), 2, "AED ") == "AED 1,050"
    assert format_money(Money(26000, "USD"), 2, "USD ") == "USD 260"
    assert format_money(Money(28550, "GBP"), 2, "£") == "£285.50"
    assert format_money(Money(1234, "KWD"), 3) == "KWD 1.234"
    assert format_money(Money(-500, "EUR"), 2, "€") == "-€5"


@given(st.integers(min_value=-(10**12), max_value=10**12), st.sampled_from([0, 2, 3]))
def test_parse_and_format_round_trip(amount: int, minor_units: int) -> None:
    money = Money(amount, "XXX")
    text = format_money(money, minor_units, "").replace(",", "")
    assert parse_major(text, "XXX", minor_units) == money


# ------------------------------------------------------------------ ids


def test_uuid7_shape_and_order() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7 and second.version == 7
    assert first.variant == uuid.RFC_4122
    assert first < second
    assert abs(uuid7_timestamp_ms(first) - time.time() * 1000) < 5000


# ------------------------------------------------------------------ encryption


def test_encryption_round_trip_and_binding() -> None:
    value = crypto.encrypt_text("secret", "students:learning_needs:abc")
    assert b"secret" not in value.ciphertext
    assert crypto.decrypt_text(value, "students:learning_needs:abc") == "secret"
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_text(value, "students:learning_needs:OTHER")  # copied onto another row: refused


def test_encryption_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    old = crypto.encrypt_text("x", "aad")
    assert old.key_id == "test-k1"
    monkeypatch.setattr(get_config(), "active_encryption_key_id", "test-k2")
    new = crypto.encrypt_text("y", "aad")
    assert new.key_id == "test-k2"
    assert crypto.decrypt_text(old, "aad") == "x"  # old ciphertexts stay readable
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_text(crypto.EncryptedValue(old.ciphertext, "missing"), "aad")


# ------------------------------------------------------------------ normalisation


def test_phone_normalisation() -> None:
    assert normalize_phone("+971 50 123 4567") == "+971501234567"
    assert normalize_phone("050 123 4567", "AE") == "+971501234567"
    assert normalize_phone("+1 (202) 555-0143") == "+12025550143"  # parsed only; never decides a market
    with pytest.raises(ValidationFailed):
        normalize_phone("12345")
    with pytest.raises(ValidationFailed):
        normalize_phone("not a phone")


def test_email_normalisation() -> None:
    assert normalize_email("  Parent.Name@Example.COM ") == "parent.name@example.com"
    with pytest.raises(ValidationFailed):
        normalize_email("not-an-email")


# ------------------------------------------------------------------ time zones


def test_timezones() -> None:
    assert validate_timezone("Asia/Dubai") == "Asia/Dubai"
    with pytest.raises(InvalidTimezone):
        validate_timezone("Dubai")
    summer = to_local(datetime(2026, 7, 1, 12, 0, tzinfo=UTC), "Europe/London")
    winter = to_local(datetime(2026, 12, 1, 12, 0, tzinfo=UTC), "Europe/London")
    assert summer.hour == 13 and winter.hour == 12  # daylight saving handled
    with pytest.raises(ValueError):
        to_local(datetime(2026, 1, 1), "Europe/London")


# ------------------------------------------------------------------ logging


def test_log_redaction() -> None:
    redacted = redact_value(
        {"note": "call +971 50 123 4567 or mail a@b.com", "password": "x", "nested": {"token": "t"}}
    )
    assert "+971" not in redacted["note"] and "a@b.com" not in redacted["note"]
    assert redacted["password"] == REDACTED
    assert redacted["nested"]["token"] == REDACTED
