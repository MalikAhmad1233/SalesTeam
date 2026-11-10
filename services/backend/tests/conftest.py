"""Test fixtures. Tests run against a real PostgreSQL database (never mocks).

Set MIXT_TEST_DATABASE_URL to point at an empty test database; the schema is rebuilt with the
real Alembic migrations at the start of the run. Each test runs inside a transaction that is
rolled back afterwards.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

TEST_DATABASE_URL = os.environ.get("MIXT_TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/mixt_test")
os.environ["MIXT_ENV"] = "test"
os.environ["MIXT_DATABASE_URL"] = TEST_DATABASE_URL
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
from mixt.core import crypto  # noqa: E402
from mixt.core.context import Actor  # noqa: E402
from mixt.core.db import get_session  # noqa: E402
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
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


def reset_database(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    reset_database(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def app(db: Session) -> Any:
    application = create_app()

    def _override() -> Iterator[Session]:
        yield db
        db.flush()

    application.dependency_overrides[get_session] = _override
    return application


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# ------------------------------------------------------------------ factories


@dataclass
class TestUser:
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
