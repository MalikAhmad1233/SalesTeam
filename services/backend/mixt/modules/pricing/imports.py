"""Pricing sheet import (docs/04 §15): upload, check, compare, then a person applies it.

1. A CSV with the template columns is parsed and every row checked: known currency, plan, unit and
   audience; positive quantities; totals exactly as written in the currency's units (no rounding);
   no duplicate packages; an existing book's currency, unit and plan cannot change.
2. The report compares each book with its latest version (added, removed, changed, unchanged
   packages) and lists anomalies to double-check. Nothing is stored as pricing yet.
3. Applying creates a **draft** version per book (or a new price book), with figures locked, ready
   for the normal review, approval and activation checklist. An import never assigns a market and
   never activates anything.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, ValidationFailed
from mixt.core.money import MoneyError, parse_major
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.identity.access import Access
from mixt.modules.pricing import service as pricing
from mixt.modules.pricing.models import (
    PLAN_TYPES,
    UNIT_TYPES,
    PriceBook,
    PriceBookVersion,
    PricingImportBatch,
    PricingImportRow,
)
from mixt.modules.reference import service as reference

MAX_BYTES = 512 * 1024
MAX_ROWS = 2000
REQUIRED = ("price_book_code", "currency", "plan_type", "unit_type", "quantity", "package_total")
OPTIONAL = ("tier_label", "audience", "price_book_name", "display_name", "advertised_unit_rate")
TEMPLATE = ",".join((*REQUIRED[:4], "tier_label", "audience", *REQUIRED[4:], "advertised_unit_rate"))
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")
Batch = PricingImportBatch


@dataclass
class _Book:
    code: str
    currency: str
    plan_type: str
    unit_type: str
    tier_label: str | None
    audience: str
    name: str
    entries: list[dict[str, Any]] = field(default_factory=list)


def _display(quantity: Decimal, unit: str) -> str:
    q = quantity.normalize()
    text = f"{q:f}"
    return f"{text} classes" if unit == "class" else f"{text}h"


def _package_code(quantity: Decimal, unit: str) -> str:
    return f"{quantity.normalize():f}".replace(".", "-") + ("C" if unit == "class" else "H")


def _parse(db: Session, content: bytes) -> tuple[list[tuple[int, dict[str, str], list[str]]], dict[str, _Book]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("FILE_NOT_UTF8", "Save the sheet as CSV (UTF-8).") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        raise ValidationFailed("TEMPLATE_COLUMNS_MISSING", f"Use the template columns: {TEMPLATE}", missing=missing)
    unknown = [h for h in headers if h not in REQUIRED + OPTIONAL]
    if unknown:
        raise ValidationFailed("UNKNOWN_COLUMNS", "Remove columns that are not in the template.", missing=unknown)
    currencies = {c.code: c for c in reference.list_currencies(db)}
    existing = {b.code: b for b in db.scalars(select(PriceBook))}
    rows: list[tuple[int, dict[str, str], list[str]]] = []
    books: dict[str, _Book] = {}
    for row_no, raw in enumerate(reader, start=2):
        if row_no - 1 > MAX_ROWS:
            raise ValidationFailed("TOO_MANY_ROWS", f"At most {MAX_ROWS} rows per file.")
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        errors: list[str] = []
        code = row.get("price_book_code", "").upper()
        currency = row.get("currency", "").upper()
        plan, unit = row.get("plan_type", "").lower(), row.get("unit_type", "").lower()
        audience = (row.get("audience") or "public").lower()
        if not _CODE.match(code):
            errors.append("price_book_code: use capital letters, digits and hyphens, e.g. 'UK-GBP-TIER-C'")
        if currency not in currencies:
            errors.append(f"currency: {currency!r} is not a known ISO currency")
        if plan not in PLAN_TYPES or plan == "custom":
            errors.append("plan_type: standard, premium or promotional")
        if unit not in UNIT_TYPES:
            errors.append("unit_type: hour or class")
        if audience not in ("public", "restricted"):
            errors.append("audience: public or restricted")
        quantity: Decimal | None = None
        try:
            quantity = Decimal(row.get("quantity", ""))
            if quantity <= 0 or quantity != quantity.quantize(Decimal("0.01")):
                errors.append("quantity: a positive number with at most 2 decimals")
                quantity = None
        except InvalidOperation:
            errors.append("quantity: not a number")
        total = advertised = None
        if currency in currencies:
            minor = currencies[currency].minor_units
            try:
                total = parse_major(row.get("package_total", ""), currency, minor).amount_minor
                if total <= 0:
                    errors.append("package_total: must be positive")
            except MoneyError as exc:
                errors.append(f"package_total: {exc}")
            if row.get("advertised_unit_rate"):
                try:
                    advertised = parse_major(row["advertised_unit_rate"], currency, minor).amount_minor
                except MoneyError as exc:
                    errors.append(f"advertised_unit_rate: {exc}")
        book_row = existing.get(code)
        if book_row is not None and not errors:
            for field_name, theirs, ours in (
                ("currency", book_row.currency_code, currency),
                ("unit_type", book_row.unit_type, unit),
                ("plan_type", book_row.plan_type, plan),
            ):
                if theirs != ours:
                    errors.append(f"{field_name}: {code} is {theirs}; a price book's {field_name} never changes")
        if not errors:
            book = books.setdefault(
                code,
                _Book(
                    code,
                    currency,
                    plan,
                    unit,
                    row.get("tier_label") or None,
                    audience,
                    row.get("price_book_name") or code,
                ),
            )
            if (book.currency, book.plan_type, book.unit_type) != (currency, plan, unit):
                errors.append(f"{code}: every row of a price book needs the same currency, plan and unit")
            elif quantity is not None and total is not None:
                if any(e["quantity"] == quantity for e in book.entries):
                    errors.append(f"quantity: {code} already has a {quantity.normalize():f} package in this file")
                else:
                    book.entries.append(
                        {
                            "quantity": quantity,
                            "total": total,
                            "advertised": advertised,
                            "display": row.get("display_name") or _display(quantity, unit),
                        }
                    )
        rows.append((row_no, row, errors))
    if not rows:
        raise ValidationFailed("FILE_EMPTY", "The sheet has no rows.")
    return rows, books


def q(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _diff(db: Session, book: _Book) -> dict[str, Any]:
    existing = db.scalar(select(PriceBook).where(PriceBook.code == book.code))
    if existing is None:
        return {"is_new": True, "compared_with": None}
    latest = db.scalar(
        select(PriceBookVersion)
        .where(PriceBookVersion.price_book_id == existing.id)
        .order_by(PriceBookVersion.version_no.desc())
    )
    before = {Decimal(e.quantity): e.package_total_minor for e in pricing.entries_of(db, latest.id)} if latest else {}
    after = {e["quantity"]: e["total"] for e in book.entries}
    return {
        "is_new": False,
        "compared_with": f"version {latest.version_no} ({latest.status})" if latest else None,
        "added": [{"quantity": q(k), "total_minor": after[k]} for k in sorted(set(after) - set(before))],
        "removed": [{"quantity": q(k), "total_minor": before[k]} for k in sorted(set(before) - set(after))],
        "changed": [
            {"quantity": q(k), "from_minor": before[k], "to_minor": after[k]}
            for k in sorted(set(before) & set(after))
            if before[k] != after[k]
        ],
        "unchanged": sum(1 for k in set(before) & set(after) if before[k] == after[k]),
    }


def _new_entries(book: _Book) -> list[pricing.NewEntry]:
    return [
        pricing.NewEntry(
            package_code=_package_code(e["quantity"], book.unit_type),
            display_name=e["display"],
            quantity=e["quantity"],
            package_total_minor=e["total"],
            advertised_unit_rate_minor=e["advertised"],
        )
        for e in book.entries
    ]


def validate(db: Session, actor: Actor, access: Access, filename: str, content: bytes) -> PricingImportBatch:
    access.require_somewhere("pricing.import")
    if len(content) > MAX_BYTES:
        raise ValidationFailed("FILE_TOO_LARGE", f"At most {MAX_BYTES // 1024} KB per file.")
    rows, books = _parse(db, content)
    report_books = []
    for book in books.values():
        existing = db.scalar(select(PriceBook).where(PriceBook.code == book.code))
        notes = pricing.anomalies(
            db, existing or PriceBook(code=book.code, unit_type=book.unit_type), _new_entries(book)
        )
        report_books.append(
            {
                "code": book.code,
                "name": book.name,
                "currency": book.currency,
                "plan_type": book.plan_type,
                "unit_type": book.unit_type,
                "tier_label": book.tier_label,
                "audience": book.audience,
                "packages": len(book.entries),
                "diff": _diff(db, book),
                "anomalies": notes,
            }
        )
    error_count = sum(1 for _, _, e in rows if e)
    batch = PricingImportBatch(
        filename=filename[:200],
        uploaded_by=actor.principal_id,
        status="invalid" if error_count else "validated",
        report={"books": report_books, "rows": len(rows)},
        error_count=error_count,
    )
    db.add(batch)
    db.flush()
    for row_no, raw, errors in rows:
        db.add(PricingImportRow(batch_id=batch.id, row_no=row_no, raw=raw, errors=errors))
    db.flush()
    audit.record(
        db, actor, "pricing_import_validated", "pricing_import", batch.id, {"rows": len(rows), "errors": error_count}
    )
    return batch


def get_batch(db: Session, access: Access, batch_id: uuid.UUID) -> tuple[PricingImportBatch, list[PricingImportRow]]:
    access.require_somewhere("pricing.import")
    batch = db.get(PricingImportBatch, batch_id)
    if batch is None:
        raise NotFound("IMPORT_NOT_FOUND", "Import not found.")
    rows = list(
        db.scalars(
            select(PricingImportRow).where(PricingImportRow.batch_id == batch.id).order_by(PricingImportRow.row_no)
        )
    )
    return batch, rows


def apply(
    db: Session,
    actor: Actor,
    access: Access,
    batch_id: uuid.UUID,
    *,
    change_type: str,
    source_document: str,
    source_received_on: date,
    change_summary: str,
) -> PricingImportBatch:
    """Create draft versions (and new price books) from a validated sheet. Nothing becomes active."""
    batch, rows = get_batch(db, access, batch_id)
    if batch.status != "validated":
        raise Conflict("IMPORT_NOT_APPLICABLE", f"Only a validated import can be applied (this one is {batch.status}).")
    if change_type not in ("price_change", "correction"):
        raise ValidationFailed("INVALID_CHANGE_TYPE", "Say whether this is a price change or a correction.")
    if len(source_document.strip()) < 3 or len(change_summary.strip()) < 10:
        raise ValidationFailed("SOURCE_REQUIRED", "Name the source document and summarise the change.")
    content = "\n".join(
        [",".join(REQUIRED + OPTIONAL)]
        + [",".join(_csv_cell(r.raw.get(c, "")) for c in REQUIRED + OPTIONAL) for r in rows]
    )
    _rows, books = _parse(db, content.encode("utf-8"))  # re-check against the database as it is now
    created: list[str] = []
    for book in books.values():
        existing = db.scalar(select(PriceBook).where(PriceBook.code == book.code))
        entries = _new_entries(book)
        if existing is None:
            new_book = PriceBook(
                code=book.code,
                name=book.name,
                currency_code=book.currency,
                plan_type=book.plan_type,
                tier_label=book.tier_label,
                unit_type=book.unit_type,
                audience=book.audience,
            )
            db.add(new_book)
            db.flush()
            version = pricing.create_version(
                db,
                actor,
                new_book,
                entries,
                change_type="initial",
                supersedes=None,
                source_document=source_document,
                source_received_on=source_received_on,
                change_summary=change_summary,
                unit_definition_ref=None,  # Mixt confirms the unit definition before activation (G-04)
            )
        elif change_type == "correction":
            latest = db.scalar(
                select(PriceBookVersion)
                .where(PriceBookVersion.price_book_id == existing.id)
                .order_by(PriceBookVersion.version_no.desc())
            )
            if latest is None:  # pragma: no cover - every book has a version
                raise Conflict("NO_VERSION", f"{existing.code} has no version to correct.")
            view, _notes = pricing.create_correction(
                db,
                actor,
                access_for_correction(access),
                latest.id,
                entries,
                source_document,
                source_received_on,
                change_summary,
            )
            version = view.version
        else:
            version = pricing.create_version(
                db,
                actor,
                existing,
                entries,
                change_type="price_change",
                supersedes=None,
                source_document=source_document,
                source_received_on=source_received_on,
                change_summary=change_summary,
                unit_definition_ref=None,
            )
        created.append(str(version.id))
    batch.status, batch.applied_by, batch.applied_at = "applied", actor.principal_id, now_utc()
    batch.applied_version_ids = created
    db.flush()
    audit.record(
        db, actor, "pricing_import_applied", "pricing_import", batch.id, {"versions": created, "change": change_type}
    )
    return batch


def access_for_correction(access: Access) -> Access:
    """Corrections from an import need the correction permission as well as the import permission."""
    access.require_somewhere("pricing.version.correct")
    return access


def _csv_cell(value: Any) -> str:
    text = str(value)
    return '"' + text.replace('"', '""') + '"' if any(ch in text for ch in ',"\n') else text


def discard(db: Session, actor: Actor, access: Access, batch_id: uuid.UUID) -> PricingImportBatch:
    batch, _rows = get_batch(db, access, batch_id)
    if batch.status not in ("validated", "invalid"):
        raise Conflict("IMPORT_NOT_DISCARDABLE", f"This import is {batch.status}.")
    batch.status = "discarded"
    db.flush()
    audit.record(db, actor, "pricing_import_discarded", "pricing_import", batch.id, {})
    return batch
