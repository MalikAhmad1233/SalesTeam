"""Normalisation of contact details.

A phone number's country code is used only to *parse* a number; it is never used to decide a
customer's market (ADR-13). E.g. a +1 number says nothing about a US market.
"""

from __future__ import annotations

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from mixt.core.errors import ValidationFailed


def normalize_phone(raw: str, region_hint: str | None = None) -> str:
    """Return the number in E.164 form or raise ``ValidationFailed``."""
    try:
        parsed = phonenumbers.parse(raw, region_hint.upper() if region_hint else None)
    except phonenumbers.NumberParseException as exc:
        raise ValidationFailed(
            "INVALID_PHONE_NUMBER",
            "Phone number could not be parsed; include the international prefix (e.g. +971...).",
        ) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationFailed("INVALID_PHONE_NUMBER", "Phone number is not valid.")
    return str(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164))


def normalize_email(raw: str) -> str:
    try:
        result = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValidationFailed("INVALID_EMAIL", "Email address is not valid.") from exc
    return result.normalized.lower()
