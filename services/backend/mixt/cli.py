"""Operational commands.

    python -m mixt.cli create-owner --email owner@example.com --name "Owner Name"

The password is read from the MIXT_OWNER_PASSWORD environment variable or prompted for; it is
never passed on the command line (where it would end up in shell history).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time

import mixt.wiring  # noqa: F401  (tables, event consumers, validators)
from mixt.core.config import get_config
from mixt.core.context import SYSTEM_ACTOR
from mixt.core.db import _sessionmaker_for
from mixt.core.errors import DomainError
from mixt.modules.events import service as events
from mixt.modules.identity import service as identity


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


def dispatch_once() -> tuple[events.DispatchResult, events.ActionRunResult]:
    """Deliver pending events and run due scheduled actions once, in one transaction."""
    session = _sessionmaker_for(get_config().database_url)()
    try:
        delivered = events.dispatch_outbox(session)
        actions = events.run_due_actions(session)
        session.commit()
        return delivered, actions
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _worker(interval: float, iterations: int | None) -> int:
    """Simple polling worker. Celery queues take over when external channels arrive (Phase 3)."""
    count = 0
    while iterations is None or count < iterations:
        delivered, actions = dispatch_once()
        if delivered.delivered or delivered.failed or actions.done or actions.failed:
            print(
                f"events delivered={delivered.delivered} failed={delivered.failed} "
                f"actions done={actions.done} failed={actions.failed}",
                flush=True,
            )
        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mixt")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("create-owner", help="Create the first Owner account (only when no users exist)")
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    sub.add_parser("dispatch-once", help="Deliver pending events and run due scheduled actions once")
    worker = sub.add_parser("worker", help="Keep delivering events and running due actions")
    worker.add_argument("--interval", type=float, default=5.0, help="Seconds between polls")
    worker.add_argument("--iterations", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "create-owner":
        return _create_owner(args.email, args.name)
    if args.command == "dispatch-once":
        delivered, actions = dispatch_once()
        print(
            f"events delivered={delivered.delivered} failed={delivered.failed} "
            f"actions done={actions.done} failed={actions.failed}"
        )
        return 0
    if args.command == "worker":
        return _worker(args.interval, args.iterations)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
