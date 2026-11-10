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

import mixt.models  # noqa: F401  (registers every table so foreign keys resolve)
from mixt.core.config import get_config
from mixt.core.context import SYSTEM_ACTOR
from mixt.core.db import _sessionmaker_for
from mixt.core.errors import DomainError
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mixt")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("create-owner", help="Create the first Owner account (only when no users exist)")
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-owner":
        return _create_owner(args.email, args.name)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
