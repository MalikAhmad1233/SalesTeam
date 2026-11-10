"""Database roles and privileges (ADR-07, IN-20).

The application never runs with schema-changing rights. Three roles are used:

* **migration owner** (``MIXT_MIGRATION_DATABASE_URL``): owns the schema, runs Alembic and then
  :func:`apply_grants`. Only the ``migrate`` command uses it.
* **application role** (``MIXT_DATABASE_URL``): reads and writes rows, nothing else. No DDL, no
  TRUNCATE, read-only access to ``alembic_version``, and on append-only tables (audit log, consent
  history) only SELECT and INSERT. Append-only is therefore enforced twice: by privileges here and
  by the database triggers from migration 0001.
* **read-only role**: SELECT only, used for backups and reporting.

Append-only tables are found from the database itself (tables guarded by the
``reject_modification()`` trigger), so a new append-only table is covered automatically.

:func:`runtime_role_problems` is what the API and worker run at start-up: in staging and production
they refuse to start with an over-privileged role.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Connection, text

SCHEMA = "public"
APPEND_ONLY_TRIGGER_FUNCTION = "reject_modification"
# Tables the application may read but never write.
READ_ONLY_FOR_APP = ("alembic_version",)
_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class RoleError(RuntimeError):
    """A role is missing, misnamed or would end up over-privileged."""


@dataclass(frozen=True)
class GrantReport:
    app_role: str
    readonly_role: str | None
    tables: int
    append_only: tuple[str, ...]


def _role(name: str) -> str:
    if not _ROLE_RE.match(name):
        raise RoleError(f"invalid role name {name!r}: use lowercase letters, digits and underscores")
    return f'"{name}"'


def append_only_tables(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT c.relname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE p.proname = :fn AND n.nspname = :schema AND NOT t.tgisinternal
            ORDER BY c.relname
            """
        ),
        {"fn": APPEND_ONLY_TRIGGER_FUNCTION, "schema": SCHEMA},
    )
    return list(rows.scalars())


def _tables(conn: Connection) -> list[str]:
    rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = :schema ORDER BY tablename"), {"schema": SCHEMA}
    )
    return list(rows.scalars())


def role_exists(conn: Connection, name: str) -> bool:
    return bool(conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}).scalar())


def apply_grants(conn: Connection, app_role: str, readonly_role: str | None = None) -> GrantReport:
    """Reset the application (and read-only) role's privileges to exactly the intended set.

    Idempotent; run by the migration owner after every migration. Roles must already exist
    (they are created by whoever administers the database server, with their own passwords).
    """
    current = conn.execute(text("SELECT current_user")).scalar_one()
    roles = [r for r in (app_role, readonly_role) if r]
    for name in roles:
        _role(name)
        if name == current:
            raise RoleError(f"{name!r} is the migration role; the application must use a separate role")
        if not role_exists(conn, name):
            raise RoleError(f"role {name!r} does not exist; create it first (CREATE ROLE {name} LOGIN PASSWORD ...)")
    if readonly_role == app_role:
        raise RoleError("the read-only role must differ from the application role")

    app = _role(app_role)
    append_only = append_only_tables(conn)
    tables = _tables(conn)
    statements = [
        f"REVOKE CREATE ON SCHEMA {SCHEMA} FROM PUBLIC",
        f"GRANT USAGE ON SCHEMA {SCHEMA} TO {app}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {app}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {app}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO {app}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {app}",
    ]
    statements += [f'REVOKE UPDATE, DELETE ON TABLE {SCHEMA}."{t}" FROM {app}' for t in append_only]
    statements += [
        f'REVOKE INSERT, UPDATE, DELETE ON TABLE {SCHEMA}."{t}" FROM {app}' for t in READ_ONLY_FOR_APP if t in tables
    ]
    if readonly_role:
        ro = _role(readonly_role)
        statements += [
            f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ro}",
            f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {ro}",
            f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {ro}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {ro}",
            f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {ro}",
        ]
    for statement in statements:
        conn.execute(text(statement))
    return GrantReport(app_role, readonly_role, len(tables), tuple(append_only))


def runtime_role_problems(conn: Connection) -> list[str]:
    """Ways the connected role has more rights than the application needs (empty = fine)."""
    problems: list[str] = []
    role = conn.execute(
        text(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication "
            "FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    flags = {
        "superuser": role.rolsuper,
        "can create roles": role.rolcreaterole,
        "can create databases": role.rolcreatedb,
        "bypasses row-level security": role.rolbypassrls,
        "replication": role.rolreplication,
    }
    problems += [f"role {role.rolname} is {label}" for label, on in flags.items() if on]
    if conn.execute(text("SELECT has_schema_privilege(current_user, :s, 'CREATE')"), {"s": SCHEMA}).scalar():
        problems.append(f"role {role.rolname} can create objects in schema {SCHEMA}")
    owned = conn.execute(
        text(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND c.relkind IN ('r', 'p') AND pg_has_role(current_user, c.relowner, 'USAGE')
            ORDER BY c.relname
            """
        ),
        {"s": SCHEMA},
    ).scalars()
    owned_list = list(owned)
    if owned_list:
        problems.append(f"role {role.rolname} owns {len(owned_list)} table(s), e.g. {owned_list[0]}")
    truncatable = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relkind IN ('r', 'p') AND has_table_privilege(current_user, c.oid, 'TRUNCATE') "
            "ORDER BY c.relname"
        ),
        {"s": SCHEMA},
    ).scalars()
    truncatable_list = list(truncatable)
    if truncatable_list:
        problems.append(f"role {role.rolname} can TRUNCATE {len(truncatable_list)} table(s)")
    for table in append_only_tables(conn):
        qualified = f"{SCHEMA}.{table}"
        for privilege in ("UPDATE", "DELETE"):
            if conn.execute(
                text("SELECT has_table_privilege(current_user, :t, :p)"), {"t": qualified, "p": privilege}
            ).scalar():
                problems.append(f"role {role.rolname} can {privilege} append-only table {table}")
    return problems
