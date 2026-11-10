"""Test fixtures. Tests run against a real PostgreSQL database (never mocks).

Set MIXT_TEST_DATABASE_URL to point at an empty test database (as a role that can create roles,
e.g. the server's superuser); the schema is rebuilt with the real Alembic migrations at the start of
the run. Each test runs inside a transaction that is rolled back afterwards.

Tests act as the least-privileged **application role** (``mixt_app_test``), exactly like the API in
staging and production: data access only, no DDL, no TRUNCATE, append-only tables insert-only.
Only tests that must simulate a database administrator use ``owner_db``.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import make_url

TEST_DATABASE_URL = os.environ.get("MIXT_TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/mixt_test")
APP_ROLE, APP_ROLE_PASSWORD, READONLY_ROLE = "mixt_app_test", "mixt-app-test-only", "mixt_readonly_test"
APP_DATABASE_URL = (
    make_url(TEST_DATABASE_URL).set(username=APP_ROLE, password=APP_ROLE_PASSWORD).render_as_string(hide_password=False)
)
os.environ["MIXT_ENV"] = "test"
os.environ["MIXT_DATABASE_URL"] = APP_DATABASE_URL
os.environ["MIXT_ENCRYPTION_KEYS"] = json.dumps(
    {"test-k1": base64.b64encode(b"\x01" * 32).decode(), "test-k2": base64.b64encode(b"\x02" * 32).decode()}
)
os.environ["MIXT_ACTIVE_ENCRYPTION_KEY_ID"] = "test-k1"
os.environ["MIXT_COOKIE_SECURE"] = "true"
os.environ["MIXT_LOG_JSON"] = "false"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from mixt.api.app import create_app  # noqa: E402
from mixt.core import crypto, db_roles, ratelimit, schema  # noqa: E402
from mixt.core.config import get_config  # noqa: E402
from mixt.core.context import Actor  # noqa: E402
from mixt.core.db import get_session, session_scope_factory  # noqa: E402
from mixt.modules.identity import mfa, passwords  # noqa: E402
from mixt.modules.identity.models import (  # noqa: E402
    Principal,
    PrincipalRole,
    Role,
    Team,
    TeamMember,
    User,
    UserMfaFactor,
)
from mixt.modules.reference.models import Market  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PASSWORD = "Correct-Horse-Battery-42"


def alembic_config(url: str) -> Config:
    return schema.alembic_config(url)


def reset_database(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def ensure_test_roles(conn: Any) -> None:
    for role, password in ((APP_ROLE, APP_ROLE_PASSWORD), (READONLY_ROLE, None)):
        if not db_roles.role_exists(conn, role):
            login = f"LOGIN PASSWORD '{password}'" if password else "NOLOGIN"
            conn.execute(text(f"CREATE ROLE {role} {login}"))


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    """The migration owner / administrator. Only for tests that need it."""
    reset_database(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        ensure_test_roles(conn)
        db_roles.apply_grants(conn, APP_ROLE, READONLY_ROLE)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def engine(owner_engine: Engine) -> Iterator[Engine]:
    """The application role: what the API and worker use."""
    eng = create_engine(APP_DATABASE_URL)
    yield eng
    eng.dispose()


def _rolled_back_session(eng: Engine) -> Iterator[Session]:
    connection = eng.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    yield from _rolled_back_session(engine)


@pytest.fixture
def owner_db(owner_engine: Engine) -> Iterator[Session]:
    yield from _rolled_back_session(owner_engine)


@pytest.fixture
def app(db: Session) -> Any:
    application = create_app()

    def _override() -> Iterator[Session]:
        yield db
        db.flush()

    @contextmanager
    def _scope() -> Iterator[Session]:
        yield db
        db.flush()

    application.dependency_overrides[get_session] = _override
    application.dependency_overrides[session_scope_factory] = lambda: _scope
    return application


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# ------------------------------------------------------------------ factories


@dataclass
class TestUser:
    __test__ = False  # a fixture type, not a test class
    user: User
    password: str
    totp_secret: str | None

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def actor(self) -> Actor:
        return Actor(principal_id=self.user.principal_id, kind="user", user_id=self.user.id)


def market_id(db: Session, country_code: str) -> uuid.UUID:
    market = db.scalar(select(Market).where(Market.country_code == country_code))
    assert market is not None
    return market.id


def make_user(
    db: Session,
    roles: list[tuple[str, uuid.UUID | None]] | None = None,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    with_mfa: bool = True,
    must_change_password: bool = False,
    status: str = "active",
) -> TestUser:
    email = email or f"user-{uuid.uuid4().hex[:10]}@mixt-test.example"
    principal = Principal(kind="user", display_name=email)
    db.add(principal)
    db.flush()
    user = User(
        principal_id=principal.id,
        email=email,
        full_name=email.split("@")[0],
        password_hash=passwords.hash_password(password),
        must_change_password=must_change_password,
        status=status,
    )
    db.add(user)
    db.flush()
    for role_key, market in roles or []:
        role = db.scalar(select(Role).where(Role.key == role_key))
        assert role is not None, role_key
        db.add(PrincipalRole(principal_id=principal.id, role_id=role.id, market_id=market, granted_by=principal.id))
    secret = None
    if with_mfa:
        secret = mfa.new_secret()
        factor = UserMfaFactor(user_id=user.id, kind="totp", secret_ciphertext=b"", key_id="")
        db.add(factor)
        db.flush()
        encrypted = crypto.encrypt_text(secret, f"user_mfa_factors:secret:{factor.id}")
        factor.secret_ciphertext, factor.key_id = encrypted.ciphertext, encrypted.key_id
        factor.confirmed_at = factor.created_at
    db.flush()
    return TestUser(user, password, secret)


def make_team(db: Session, lead: TestUser, members: list[TestUser]) -> Team:
    team = Team(name=f"team-{uuid.uuid4().hex[:8]}")
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=lead.id, team_role="lead"))
    for m in members:
        db.add(TeamMember(team_id=team.id, user_id=m.id, team_role="member"))
    db.flush()
    return team


def next_code(db: Session, user: TestUser) -> str:
    """A valid TOTP code that has not been used yet (respects replay protection)."""
    assert user.totp_secret is not None
    factor = db.scalar(select(UserMfaFactor).where(UserMfaFactor.user_id == user.id))
    step = mfa.current_step()
    if factor is not None and factor.last_used_step is not None and factor.last_used_step >= step:
        step = factor.last_used_step + 1
    return mfa.code_for_step(user.totp_secret, step)


class Api:
    """Signed-in test client that adds the CSRF header to state-changing requests."""

    def __init__(self, client: TestClient, csrf: str) -> None:
        self.client = client
        self.csrf = csrf

    def _headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf, **(extra or {})}

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, **kw)

    def post(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.client.post(url, json=json, headers=self._headers(headers))

    def patch(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.client.patch(url, json=json, headers=self._headers(headers))

    def put(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.client.put(url, json=json, headers=self._headers(headers))


def sign_in(client: TestClient, db: Session, user: TestUser) -> Api:
    response = client.post("/api/v1/auth/login", json={"email": user.user.email, "password": user.password})
    assert response.status_code == 200, response.text
    body = response.json()
    if body["mfa_state"] == "required":
        response = client.post(
            "/api/v1/auth/mfa/verify",
            json={"code": next_code(db, user)},
            headers={"X-CSRF-Token": body["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
    return Api(client, body["csrf_token"])


@pytest.fixture
def as_user(client: TestClient, db: Session) -> Any:
    def _factory(roles: list[tuple[str, uuid.UUID | None]], **kw: Any) -> tuple[Api, TestUser]:
        user = make_user(db, roles, **kw)
        return sign_in(client, db, user), user

    return _factory


@pytest.fixture
def app_factory(db: Session) -> Any:
    """Separate app/client instances, e.g. to act as two different users at once."""

    def _make() -> TestClient:
        application = create_app()

        def _override() -> Iterator[Session]:
            yield db
            db.flush()

        application.dependency_overrides[get_session] = _override
        return TestClient(application, base_url="https://testserver")

    return _make


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> Iterator[None]:
    """Rate-limit counters never leak from one test into another."""
    ratelimit.reset_memory_limiters()
    yield
    ratelimit.reset_memory_limiters()


@pytest.fixture
def config_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Change deployment configuration (MIXT_* variables) for one test."""

    def _set(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(f"MIXT_{key.upper()}", value)
        get_config.cache_clear()

    yield _set
    monkeypatch.undo()
    get_config.cache_clear()
