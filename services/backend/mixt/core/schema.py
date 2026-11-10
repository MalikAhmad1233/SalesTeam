"""Schema version helpers: where the migrations are, which revision the code expects, which one the
database has. Used by ``migrate``, the readiness check and the restore check."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Serialises concurrent `migrate` runs (e.g. two deploys at once). Arbitrary but fixed.
MIGRATION_LOCK_KEY = 7_352_011_001


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if url:
        cfg.attributes["database_url"] = url
    return cfg


@lru_cache(maxsize=1)
def expected_head() -> str | None:
    """The newest migration in this build, or None if the migrations are not shipped with it."""
    if not (BACKEND_DIR / "migrations").is_dir():
        return None
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(conn: Connection) -> str | None:
    exists = conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar()
    if not exists:
        return None
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
