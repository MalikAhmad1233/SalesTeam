"""Spreadsheet (CSV) parsing and row validation for lead imports. No database writes here."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from mixt.core.errors import ValidationFailed
from mixt.core.normalize import normalize_email, normalize_phone

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
COLUMNS = (
    "household_name",
    "guardian_first_name",
    "guardian_last_name",
    "email",
    "phone",
    "country",
    "student_first_name",
    "student_curriculum",
    "student_grade",
    "message",
    "external_id",
)


@dataclass
class RowResult:
    row: int  # 1-based data row number (header excluded)
    ok: bool
    errors: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


def parse_csv(content: bytes) -> list[dict[str, str]]:
    if len(content) > MAX_BYTES:
        raise ValidationFailed("FILE_TOO_LARGE", "Files are limited to 2 MB; split the file and import in parts.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("FILE_NOT_UTF8", "Save the spreadsheet as CSV UTF-8 and upload it again.") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationFailed("FILE_EMPTY", "The file has no header row.")
    headers = [h.strip().lower() for h in reader.fieldnames]
    unknown = [h for h in headers if h and h not in COLUMNS]
    if unknown:
        raise ValidationFailed("UNKNOWN_COLUMNS", f"Unknown columns: {', '.join(unknown)}.", allowed=list(COLUMNS))
    rows = []
    for raw in reader:
        rows.append({k.strip().lower(): (v or "").strip() for k, v in raw.items() if k})
        if len(rows) > MAX_ROWS:
            raise ValidationFailed("TOO_MANY_ROWS", f"Imports are limited to {MAX_ROWS} rows.")
    if not rows:
        raise ValidationFailed("FILE_EMPTY", "The file has a header but no rows.")
    return rows


def validate_rows(rows: list[dict[str, str]], known_countries: set[str], known_curricula: set[str]) -> list[RowResult]:
    results: list[RowResult] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(rows, start=1):
        result = RowResult(row=number, ok=True)
        name = raw.get("household_name") or raw.get("guardian_first_name")
        if not name:
            result.errors.append("household_name or guardian_first_name is required")
        country = (raw.get("country") or "").upper() or None
        if country and country not in known_countries:
            result.errors.append(f"country '{raw.get('country')}' is not an ISO code (e.g. AE, GB)")
        email = phone = None
        if raw.get("email"):
            try:
                email = normalize_email(raw["email"])
            except ValidationFailed:
                result.errors.append("email is not valid")
        if raw.get("phone"):
            try:
                phone = normalize_phone(raw["phone"], country)
            except ValidationFailed:
                result.errors.append("phone is not valid (include the international prefix)")
        if not raw.get("email") and not raw.get("phone"):
            result.errors.append("email or phone is required")
        curriculum = (raw.get("student_curriculum") or "").upper() or None
        if curriculum and curriculum not in known_curricula:
            result.errors.append(f"curriculum '{raw.get('student_curriculum')}' is not one of the confirmed curricula")
        for key in (k for k in (email, phone) if k):
            if key in seen:
                result.errors.append(f"same email/phone as row {seen[key]}")
            else:
                seen[key] = number
        result.ok = not result.errors
        result.data = {
            "household_name": raw.get("household_name") or None,
            "guardian_first_name": raw.get("guardian_first_name") or None,
            "guardian_last_name": raw.get("guardian_last_name") or None,
            "email": email,
            "phone": phone,
            "country": country,
            "student_first_name": raw.get("student_first_name") or None,
            "student_curriculum": curriculum,
            "student_grade": raw.get("student_grade") or None,
            "message": raw.get("message") or None,
            "external_id": raw.get("external_id") or None,
        }
        results.append(result)
    return results
