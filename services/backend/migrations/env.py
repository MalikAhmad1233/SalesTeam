"""Alembic environment. The database URL never comes from alembic.ini.

Migrations run as the migration owner: MIXT_MIGRATION_DATABASE_URL, falling back to MIXT_DATABASE_URL
for local development where one role does everything. In staging and production use
``python -m mixt.cli migrate``, which also takes a lock and re-applies the application role's grants.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from mixt.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = (
        config.attributes.get("database_url")
        or os.environ.get("MIXT_MIGRATION_DATABASE_URL")
        or os.environ.get("MIXT_DATABASE_URL")
    )
    if not url:
        raise RuntimeError("Set MIXT_MIGRATION_DATABASE_URL (or MIXT_DATABASE_URL locally) to run migrations")
    return str(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
