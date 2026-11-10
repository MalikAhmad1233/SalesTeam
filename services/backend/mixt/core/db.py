"""Database engine, session factory and declarative base.

Domain services use synchronous SQLAlchemy sessions (ADR-07). One session per request/job;
services never commit on their own: the caller (request dependency or job) owns the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, Engine, MetaData, Uuid, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from mixt.core.config import get_config
from mixt.core.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid7)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), nullable=False)


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def get_engine() -> Engine:
    return _engine_for(get_config().database_url)


@lru_cache(maxsize=4)
def _sessionmaker_for(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_engine_for(url), expire_on_commit=False, autoflush=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one transaction per request, committed on success."""
    session = _sessionmaker_for(get_config().database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
