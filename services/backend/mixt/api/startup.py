"""Start-up safety checks for the API and worker.

In staging and production the process refuses to start when:
* its database role can do more than read and write rows (see ``mixt.core.db_roles``), or
* the database schema is not at the revision this build was made for (run ``migrate`` first).

Locally the same findings are logged as warnings; tests skip them.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from mixt.core import db_roles, schema
from mixt.core.config import AppConfig, Environment
from mixt.core.logging import get_logger

log = get_logger("mixt.startup")


class StartupCheckFailed(RuntimeError):
    pass


def findings(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        problems = db_roles.runtime_role_problems(conn)
        revision = schema.current_revision(conn)
    head = schema.expected_head()
    if head is not None and revision != head:
        problems.append(f"database schema is at {revision or 'nothing'}, this build needs {head}: run migrate")
    return problems


def run(config: AppConfig, engine: Engine) -> list[str]:
    if config.env is Environment.TEST:
        return []
    deployed = config.env in (Environment.STAGING, Environment.PRODUCTION)
    try:
        problems = findings(engine)
    except SQLAlchemyError as exc:
        if deployed:
            raise StartupCheckFailed(f"refusing to start: database check failed ({type(exc).__name__})") from exc
        problems = [f"database not reachable yet ({type(exc).__name__}); checks skipped"]
    if problems and deployed:
        raise StartupCheckFailed("refusing to start: " + "; ".join(problems))
    for problem in problems:
        log.warning("startup_check", problem=problem)
    return problems
