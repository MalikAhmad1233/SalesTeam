"""Operational commands.

    python -m mixt.cli create-owner --email owner@example.com --name "Owner Name"
    python -m mixt.cli migrate --app-role mixt_app --readonly-role mixt_readonly
    python -m mixt.cli check-db-role
    python -m mixt.cli worker
    python -m mixt.cli verify-restore --database-url postgresql+psycopg://...

The Owner password is read from MIXT_OWNER_PASSWORD or prompted for; it is never passed on the
command line (where it would end up in shell history). ``migrate`` reads only
MIXT_MIGRATION_DATABASE_URL (or MIXT_DATABASE_URL locally): it does not need, and should not be
given, the encryption keys.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType

from alembic import command
from sqlalchemy import create_engine, pool, text

import mixt.wiring  # noqa: F401  (tables, event consumers, validators)
from mixt.core import db_roles, schema
from mixt.core.config import get_config
from mixt.core.context import SYSTEM_ACTOR
from mixt.core.db import _sessionmaker_for, get_engine
from mixt.core.errors import DomainError
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity
from mixt.modules.pricing import promotions
from mixt.ops import restore_check


def _create_owner(email: str, name: str) -> int:
    password = os.environ.get("MIXT_OWNER_PASSWORD") or getpass.getpass("Password for the Owner account: ")
    session = _sessionmaker_for(get_config().database_url)()
    try:
        user = identity.bootstrap_owner(session, SYSTEM_ACTOR, email, name, password)
        session.commit()
    except DomainError as exc:
        session.rollback()
        print(f"error: {exc.code}: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        session.close()
    print(f"Owner created: {user.email}. Sign in and set up two-step verification.")
    return 0


def _migrate(app_role: str | None, readonly_role: str | None) -> int:
    url = os.environ.get("MIXT_MIGRATION_DATABASE_URL") or os.environ.get("MIXT_DATABASE_URL")
    if not url:
        print("error: set MIXT_MIGRATION_DATABASE_URL", file=sys.stderr)
        return 2
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": schema.MIGRATION_LOCK_KEY})
        conn.commit()
        try:
            before = schema.current_revision(conn)
            conn.commit()
            cfg = schema.alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
            after = schema.current_revision(conn)
            print(f"schema: {before or 'empty'} -> {after}")
            if app_role:
                report = db_roles.apply_grants(conn, app_role, readonly_role)
                conn.commit()
                print(
                    f"grants: {report.app_role} read/write on {report.tables} tables, append-only "
                    f"{', '.join(report.append_only)}; read-only role: {report.readonly_role or 'none'}"
                )
        except db_roles.RoleError as exc:
            conn.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": schema.MIGRATION_LOCK_KEY})
            conn.commit()
    engine.dispose()
    return 0


def _check_db_role() -> int:
    with get_engine().connect() as conn:
        problems = db_roles.runtime_role_problems(conn)
    if problems:
        for problem in problems:
            print(f"problem: {problem}")
        return 1
    print("ok: the application role has data access only")
    return 0


def dispatch_once() -> tuple[events.DispatchResult, events.ActionRunResult]:
    """Deliver pending events and run due scheduled actions once, in one transaction."""
    session = _sessionmaker_for(get_config().database_url)()
    try:
        delivered = events.dispatch_outbox(session)
        actions = events.run_due_actions(session)
        promotions.expire_due(session)  # promotions end on their end date (docs/04 §9)
        session.commit()
        return delivered, actions
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class _Stop:
    requested = False

    @classmethod
    def handle(cls, _signum: int, _frame: FrameType | None) -> None:
        cls.requested = True


def _worker(interval: float, iterations: int | None, heartbeat: Path | None) -> int:
    """Polling worker. Stops cleanly on SIGTERM/SIGINT after the current batch.

    Celery queues take over when external channels arrive (Phase 3). The heartbeat file's
    modification time is used by the container health check.
    """
    _Stop.requested = False
    previous = {sig: signal.signal(sig, _Stop.handle) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return _poll(interval, iterations, heartbeat)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _poll(interval: float, iterations: int | None, heartbeat: Path | None) -> int:
    count = 0
    while not _Stop.requested and (iterations is None or count < iterations):
        delivered, actions = dispatch_once()
        if heartbeat is not None:
            heartbeat.touch()
        if delivered.delivered or delivered.failed or actions.done or actions.failed:
            print(
                f"events delivered={delivered.delivered} failed={delivered.failed} "
                f"actions done={actions.done} failed={actions.failed}",
                flush=True,
            )
        count += 1
        deadline = time.monotonic() + interval
        while (iterations is None or count < iterations) and not _Stop.requested and time.monotonic() < deadline:
            time.sleep(min(0.2, interval))
    print("worker stopped", flush=True)
    return 0


def _verify_restore(url: str, manifest: Path | None) -> int:
    expected = json.loads(manifest.read_text(encoding="utf-8")) if manifest else None
    report = restore_check.verify(url, expected)
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.ok else 1


def _backup_manifest(out: Path) -> int:
    url = os.environ.get("MIXT_BACKUP_DATABASE_URL") or get_config().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        manifest = restore_check.manifest(conn)
    engine.dispose()
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"manifest written: {out} ({len(manifest['tables'])} tables)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mixt")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("create-owner", help="Create the first Owner account (only when no users exist)")
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    migrate = sub.add_parser("migrate", help="Upgrade the schema (as the migration owner) and re-apply grants")
    migrate.add_argument("--app-role", default=os.environ.get("MIXT_APP_DB_ROLE"))
    migrate.add_argument("--readonly-role", default=os.environ.get("MIXT_READONLY_DB_ROLE"))
    sub.add_parser("check-db-role", help="Check the application's database role has data access only")
    sub.add_parser("dispatch-once", help="Deliver pending events and run due scheduled actions once")
    worker = sub.add_parser("worker", help="Keep delivering events and running due actions")
    worker.add_argument("--interval", type=float, default=5.0, help="Seconds between polls")
    worker.add_argument("--heartbeat-file", type=Path, default=None, help="Touched after every poll")
    worker.add_argument("--iterations", type=int, default=None, help=argparse.SUPPRESS)
    verify = sub.add_parser("verify-restore", help="Check a restored database: schema, audit chain, row counts")
    verify.add_argument("--database-url", required=True)
    verify.add_argument("--manifest", type=Path, default=None, help="Manifest written when the backup was taken")
    manifest = sub.add_parser("backup-manifest", help="Write table row counts and schema version for a backup")
    manifest.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "create-owner":
        return _create_owner(args.email, args.name)
    if args.command == "migrate":
        return _migrate(args.app_role, args.readonly_role)
    if args.command == "check-db-role":
        return _check_db_role()
    if args.command == "dispatch-once":
        delivered, actions = dispatch_once()
        print(
            f"events delivered={delivered.delivered} failed={delivered.failed} "
            f"actions done={actions.done} failed={actions.failed}"
        )
        return 0
    if args.command == "worker":
        return _worker(args.interval, args.iterations, args.heartbeat_file)
    if args.command == "verify-restore":
        return _verify_restore(args.database_url, args.manifest)
    if args.command == "backup-manifest":
        return _backup_manifest(args.out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
