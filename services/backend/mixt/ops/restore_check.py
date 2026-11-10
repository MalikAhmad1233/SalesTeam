"""Backup manifest and restore verification (IN-22).

A backup is only useful if it restores. ``backup.sh`` writes a manifest just before ``pg_dump``
starts; the restore check restores the dump into a scratch database and verifies it here:

* the schema is at the revision this build expects;
* every table the code knows about exists, and the integrity triggers came back;
* the audit hash chain verifies end to end;
* the audit row the manifest recorded is present with the same hash, which proves the backup holds
  everything written up to the moment the manifest was taken (the chain makes this tamper-evident);
* the US is still excluded and is not a market (BD-005).

Row counts of other tables are reported for information: the dump is taken a moment after the
manifest, so ordinary activity can change them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, create_engine, pool, text
from sqlalchemy.orm import Session

import mixt.models
from mixt.core import db_roles, schema
from mixt.modules.audit import service as audit

# Append-only guards (2 tables x 2 triggers) and the US guards from migration 0001.
EXPECTED_TRIGGERS = (
    "trg_audit_log_append_only",
    "trg_audit_log_no_truncate",
    "trg_audit_log_chain",
    "trg_consents_append_only",
    "trg_consents_no_truncate",
    "trg_markets_reject_excluded_country",
    "trg_countries_guard_exclusion",
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class RestoreReport:
    checks: list[Check] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    count_changes: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "row_counts": self.row_counts,
            "count_changes_since_manifest": self.count_changes,
        }


def _counts(conn: Connection) -> dict[str, int]:
    tables = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    ).scalars()
    # Table names come from the catalogue, quoted as identifiers.
    return {t: int(conn.execute(text(f'SELECT count(*) FROM public."{t}"')).scalar_one()) for t in tables}  # noqa: S608


def _audit_tip(conn: Connection) -> dict[str, Any]:
    row = conn.execute(text("SELECT chain_seq, row_hash FROM audit_log ORDER BY chain_seq DESC LIMIT 1")).first()
    if row is None:
        return {"rows": 0, "last_chain_seq": None, "last_hash": None}
    rows = int(conn.execute(text("SELECT count(*) FROM audit_log")).scalar_one())
    return {"rows": rows, "last_chain_seq": int(row.chain_seq), "last_hash": bytes(row.row_hash).hex()}


def manifest(conn: Connection) -> dict[str, Any]:
    """What a backup should contain, recorded just before the dump starts."""
    return {
        "taken_at": datetime.now(UTC).isoformat(),
        "schema_revision": schema.current_revision(conn),
        "tables": _counts(conn),
        "audit": _audit_tip(conn),
    }


def _check_audit_tip(conn: Connection, report: RestoreReport, expected: dict[str, Any]) -> None:
    tip = expected.get("audit") or {}
    seq, digest = tip.get("last_chain_seq"), tip.get("last_hash")
    if seq is None:
        report.add("audit_tip_present", True, "the manifest recorded an empty audit log")
        return
    row = conn.execute(text("SELECT row_hash FROM audit_log WHERE chain_seq = :s"), {"s": seq}).first()
    if row is None:
        report.add("audit_tip_present", False, f"audit entry {seq} recorded in the manifest is missing")
    elif bytes(row.row_hash).hex() != digest:
        report.add("audit_tip_present", False, f"audit entry {seq} has a different hash than recorded")
    else:
        report.add("audit_tip_present", True, f"audit entry {seq} present with the recorded hash")


def verify_connection(conn: Connection, expected: dict[str, Any] | None = None) -> RestoreReport:
    report = RestoreReport()
    head = schema.expected_head()
    revision = schema.current_revision(conn)
    report.add("schema_revision", revision is not None and revision == head, f"database {revision}, code {head}")
    if expected and expected.get("schema_revision") is not None:
        same = revision == expected["schema_revision"]
        report.add("schema_matches_manifest", same, f"manifest {expected['schema_revision']}, restored {revision}")

    present = set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())
    missing = sorted(set(mixt.models.Base.metadata.tables) - present)
    report.add("tables_present", not missing, "all tables present" if not missing else f"missing: {missing}")

    triggers = set(conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    lost = sorted(set(EXPECTED_TRIGGERS) - triggers)
    report.add("integrity_triggers", not lost, "all integrity triggers present" if not lost else f"missing: {lost}")
    append_only = db_roles.append_only_tables(conn)
    report.add("append_only_tables", set(append_only) >= {"audit_log", "consents"}, ", ".join(append_only))

    if "audit_log" in present:
        with Session(bind=conn) as session:
            chain = audit.verify_chain(session)
        detail = f"{chain.rows_checked} entries verified"
        if not chain.ok:
            detail = f"broken at entry {chain.first_broken_chain_seq}: {chain.reason}"
        report.add("audit_chain", chain.ok, detail)
        if expected:
            _check_audit_tip(conn, report, expected)

    us_market = conn.execute(text("SELECT count(*) FROM markets WHERE country_code = 'US'")).scalar_one()
    us_excluded = conn.execute(text("SELECT is_excluded FROM countries WHERE code = 'US'")).scalar()
    report.add(
        "us_not_a_market",
        us_market == 0 and us_excluded is True,
        "US excluded and not a market" if us_market == 0 and us_excluded else "US exclusion broken",
    )

    report.row_counts = _counts(conn)
    if expected:
        for table, before in (expected.get("tables") or {}).items():
            after = report.row_counts.get(table)
            if after is not None and after != before:
                report.count_changes[table] = {"manifest": before, "restored": after}
    return report


def verify(url: str, expected: dict[str, Any] | None = None) -> RestoreReport:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            return verify_connection(conn, expected)
    finally:
        engine.dispose()
