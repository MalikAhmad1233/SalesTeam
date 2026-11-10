"""Phase 1d hardening: database roles, start-up checks, readiness, rate limits, trusted proxies,
configuration rules, operational commands and the restore check."""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.requests import Request

from mixt import cli
from mixt.api import startup
from mixt.api.net import resolve_client_ip
from mixt.core import db_roles, ratelimit, schema
from mixt.core.config import AppConfig, Rate
from mixt.core.context import SYSTEM_ACTOR
from mixt.modules.audit import service as audit
from mixt.ops import restore_check
from tests.conftest import APP_ROLE, READONLY_ROLE, TEST_DATABASE_URL, make_user

KEYS = {"k1": base64.b64encode(b"\x07" * 32).decode()}


def _config(**overrides: Any) -> AppConfig:
    values: dict[str, Any] = {
        "database_url": TEST_DATABASE_URL,
        "encryption_keys": KEYS,
        "active_encryption_key_id": "k1",
    }
    values.update(overrides)
    return AppConfig(**values)


# ------------------------------------------------------------------------------- database roles


def test_app_role_has_data_access_only(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar() == APP_ROLE
        assert db_roles.runtime_role_problems(conn) == []


def test_owner_role_is_flagged_as_over_privileged(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        problems = " | ".join(db_roles.runtime_role_problems(conn))
    assert "superuser" in problems
    assert "owns" in problems
    assert "TRUNCATE" in problems
    assert "append-only table audit_log" in problems


def test_append_only_tables_are_found_from_the_triggers(engine: Engine) -> None:
    with engine.connect() as conn:
        assert db_roles.append_only_tables(conn) == ["audit_log", "consents"]


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("CREATE TABLE sneaky (id int)", "permission denied"),
        ("ALTER TABLE users ADD COLUMN sneaky int", "must be owner"),
        ("DROP TABLE tags", "must be owner"),
        ("TRUNCATE tasks", "permission denied"),
        ("UPDATE alembic_version SET version_num = 'x'", "permission denied"),
        ("CREATE ROLE sneaky", "permission denied"),
    ],
)
def test_app_role_cannot_change_the_schema(db: Session, sql: str, fragment: str) -> None:
    with pytest.raises(DBAPIError) as info, db.begin_nested():
        db.execute(text(sql))
    assert fragment in str(info.value)


def test_readonly_role_can_read_but_not_write(owner_db: Session) -> None:
    owner_db.execute(text(f"SET LOCAL ROLE {READONLY_ROLE}"))
    assert owner_db.execute(text("SELECT count(*) FROM markets")).scalar() == 13
    with pytest.raises(DBAPIError) as info, owner_db.begin_nested():
        owner_db.execute(text("INSERT INTO tags (id, name) VALUES (gen_random_uuid(), 'x')"))
    assert "permission denied" in str(info.value)


def test_apply_grants_refuses_bad_roles(owner_db: Session) -> None:
    conn = owner_db.connection()
    with pytest.raises(db_roles.RoleError, match="does not exist"):
        db_roles.apply_grants(conn, "no_such_role_here")
    with pytest.raises(db_roles.RoleError, match="invalid role name"):
        db_roles.apply_grants(conn, 'x"; DROP TABLE users; --')
    with pytest.raises(db_roles.RoleError, match="migration role"):
        db_roles.apply_grants(conn, str(conn.execute(text("SELECT current_user")).scalar()))
    with pytest.raises(db_roles.RoleError, match="must differ"):
        db_roles.apply_grants(conn, APP_ROLE, APP_ROLE)


# ------------------------------------------------------------------------------- start-up checks


def test_startup_refuses_over_privileged_role_in_staging(owner_engine: Engine) -> None:
    config = _config(env="staging", redis_url="redis://localhost:1/0")
    with pytest.raises(startup.StartupCheckFailed, match="superuser"):
        startup.run(config, owner_engine)


def test_startup_accepts_app_role_in_staging(engine: Engine) -> None:
    config = _config(env="staging", redis_url="redis://localhost:1/0")
    assert startup.run(config, engine) == []


def test_startup_warns_locally_and_skips_in_tests(owner_engine: Engine) -> None:
    assert startup.run(_config(env="local"), owner_engine)
    assert startup.run(_config(env="test"), owner_engine) == []


def test_startup_needs_a_reachable_database_when_deployed() -> None:
    unreachable = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    assert "not reachable" in startup.run(_config(env="local"), unreachable)[0]
    with pytest.raises(startup.StartupCheckFailed, match="database check failed"):
        startup.run(_config(env="staging", redis_url="redis://localhost:1/0"), unreachable)


def test_startup_refuses_a_schema_that_is_behind(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema, "expected_head", lambda: "9999")
    config = _config(env="production", redis_url="redis://localhost:1/0")
    with pytest.raises(startup.StartupCheckFailed, match="run migrate"):
        startup.run(config, engine)


def test_readiness_reports_schema(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok", "schema": "ok"}
    monkeypatch.setattr(schema, "expected_head", lambda: "9999")
    behind = client.get("/api/v1/health/ready")
    assert behind.status_code == 503
    assert behind.json()["schema"] == "behind"


# ------------------------------------------------------------------------------- configuration


def test_staging_needs_redis_and_secure_settings() -> None:
    with pytest.raises(ValidationError, match="MIXT_REDIS_URL"):
        _config(env="staging")
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        _config(env="production", redis_url="redis://r", cookie_secure=False)
    with pytest.raises(ValidationError, match="cannot be switched off"):
        _config(env="production", redis_url="redis://r", rate_limits_enabled=False)
    with pytest.raises(ValidationError, match="local and test"):
        _config(env="staging", redis_url="redis://r", sso_issuer_overrides={"google": "https://idp.test"})
    with pytest.raises(ValidationError, match="https"):
        _config(env="staging", redis_url="redis://r", public_base_url="http://app.example.com")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rate_login_per_ip", "lots"),
        ("rate_login_per_ip", "0/1m"),
        ("trusted_proxies", ["not-a-network"]),
        ("public_base_url", "https://app.example.com/path"),
    ],
)
def test_bad_configuration_is_rejected(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        _config(**{field: value})


def test_rate_parsing() -> None:
    assert Rate.parse("10/15m") == Rate(10, 900)
    assert Rate.parse("5 / h") == Rate(5, 3600)
    assert Rate.parse("1200/1m") == Rate(1200, 60)
    assert _config(sso_allowed_domains=[" @Mixt.Example ", ""]).sso_allowed_domains == ["mixt.example"]


# ------------------------------------------------------------------------------- rate limiting


class FakeClock:
    def __init__(self) -> None:
        self.ms = 1_000_000.0

    def __call__(self) -> float:
        return self.ms

    def advance(self, seconds: float) -> None:
        self.ms += seconds * 1000


def test_gcra_allows_a_burst_then_a_steady_rate() -> None:
    clock = FakeClock()
    limiter = ratelimit.MemoryRateLimiter(clock)
    rate = Rate(3, 60)  # 3 per minute: one every 20 s, burst of 3
    results = [limiter.hit("t", "alice", rate) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results[:3]] == [2, 1, 0]
    assert results[3].retry_after_seconds == 20
    clock.advance(19)
    assert not limiter.hit("t", "alice", rate).allowed
    clock.advance(1)
    assert limiter.hit("t", "alice", rate).allowed
    assert limiter.hit("t", "bob", rate).allowed  # separate key
    assert limiter.hit("other", "alice", rate).allowed  # separate limit


def test_keys_do_not_contain_personal_data() -> None:
    key = ratelimit.key_for("login_per_account", "someone@example.com")
    assert "someone" not in key and key.startswith("mixt:rl:login_per_account:")


def test_disabled_limiter_always_allows() -> None:
    limiter = ratelimit.limiter_for(_config(rate_limits_enabled=False))
    assert all(limiter.hit("t", "x", Rate(1, 60)).allowed for _ in range(5))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    """MIXT_TEST_REDIS_URL (CI service), or a throwaway local redis-server, else skip."""
    url = os.environ.get("MIXT_TEST_REDIS_URL")
    if url:
        yield url
        return
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("no Redis available (set MIXT_TEST_REDIS_URL)")
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603
        [binary, "--port", str(port), "--save", "", "--appendonly", "no"], stdout=subprocess.DEVNULL
    )
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_redis_limiter_shares_counts_between_instances(redis_url: str) -> None:
    rate = Rate(3, 60)
    identity = f"user-{time.time_ns()}"
    first, second = ratelimit.RedisRateLimiter(redis_url), ratelimit.RedisRateLimiter(redis_url)
    assert first.ping()
    assert first.hit("t", identity, rate).allowed
    assert second.hit("t", identity, rate).allowed  # another API process sees the same counter
    assert first.hit("t", identity, rate).allowed
    refused = second.hit("t", identity, rate)
    assert not refused.allowed and 1 <= refused.retry_after_seconds <= 20


def test_redis_outage_lets_requests_through() -> None:
    limiter = ratelimit.RedisRateLimiter(f"redis://127.0.0.1:{_free_port()}/0")
    assert not limiter.ping()
    assert all(limiter.hit("t", "x", Rate(1, 60)).allowed for _ in range(3))


def test_login_is_limited_per_account(client: TestClient) -> None:
    for _ in range(10):
        response = client.post("/api/v1/auth/login", json={"email": "Nobody@Example.com", "password": "wrong-one"})
        assert response.status_code == 401
    refused = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-one"})
    assert refused.status_code == 429
    assert refused.headers["content-type"] == "application/problem+json"
    assert int(refused.headers["Retry-After"]) > 0
    body = refused.json()
    assert body["code"] == "RATE_LIMITED" and body["limit"] == "login_per_account"


def test_login_is_limited_per_address(app: Any) -> None:
    with TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000)) as c:
        for i in range(30):
            assert c.post("/api/v1/auth/login", json={"email": f"n{i}@example.com", "password": "x"}).status_code == 401
        refused = c.post("/api/v1/auth/login", json={"email": "n99@example.com", "password": "x"})
    assert refused.status_code == 429 and refused.json()["limit"] == "login_per_ip"
    with TestClient(app, base_url="https://testserver", client=("203.0.113.10", 4000)) as other:
        assert other.post("/api/v1/auth/login", json={"email": "n99@example.com", "password": "x"}).status_code == 401


def test_every_api_request_counts_per_address(app: Any, config_env: Any) -> None:
    config_env(rate_api_per_ip="3/1m")
    with TestClient(app, base_url="https://testserver", client=("198.51.100.7", 4000)) as c:
        assert [c.get("/api/v1/reference/markets").status_code for _ in range(3)] == [401, 401, 401]
        refused = c.get("/api/v1/reference/markets")
        assert refused.status_code == 429 and refused.headers["Retry-After"]
        assert refused.json()["code"] == "RATE_LIMITED"
        assert c.get("/api/v1/health").status_code == 200  # health checks are never limited


def test_mfa_codes_are_limited_per_session(client: TestClient, db: Session, config_env: Any) -> None:
    # Account lockout (5 failures) normally ends the session first; the limit is a second line of defence.
    config_env(rate_mfa_per_session="3/5m")
    user = make_user(db)
    body = client.post("/api/v1/auth/login", json={"email": user.user.email, "password": user.password}).json()
    headers = {"X-CSRF-Token": body["csrf_token"]}
    codes = [
        client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=headers).status_code for _ in range(3)
    ]
    assert set(codes) == {401}
    refused = client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=headers)
    assert refused.status_code == 429 and refused.json()["limit"] == "mfa_per_session"


def test_signed_in_users_have_a_request_budget(as_user: Any, config_env: Any) -> None:
    config_env(rate_api_per_user="3/1m")
    api, _ = as_user([("sales_rep", None)])  # the two-step verification call is the first request
    assert api.get("/api/v1/auth/me").status_code == 200
    assert api.get("/api/v1/auth/me").status_code == 200
    refused = api.get("/api/v1/auth/me")
    assert refused.status_code == 429 and refused.json()["limit"] == "api_per_user"


# ------------------------------------------------------------------------------- trusted proxies


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers, "method": "GET", "path": "/"})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.5", None, "203.0.113.5"),
        ("203.0.113.5", "1.2.3.4", "203.0.113.5"),  # untrusted peer: header ignored
        ("10.0.0.2", "198.51.100.1", "198.51.100.1"),  # trusted proxy: header believed
        ("10.0.0.2", "6.6.6.6, 198.51.100.1", "198.51.100.1"),  # client-supplied prefix ignored
        ("10.0.0.2", "198.51.100.1, 10.0.0.3", "198.51.100.1"),  # two trusted hops
        ("10.0.0.2", "garbage, 10.0.0.3", "10.0.0.2"),
        ("10.0.0.2", None, "10.0.0.2"),
        ("testclient", "1.2.3.4", None),
    ],
)
def test_client_address_behind_trusted_proxies(peer: str, forwarded: str | None, expected: str | None) -> None:
    assert resolve_client_ip(_request(peer, forwarded), ["10.0.0.0/8"]) == expected


# ------------------------------------------------------------------------------- operational commands


def test_migrate_command_upgrades_and_reapplies_grants(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], owner_engine: Engine
) -> None:
    monkeypatch.setenv("MIXT_MIGRATION_DATABASE_URL", TEST_DATABASE_URL)
    assert cli.main(["migrate", "--app-role", APP_ROLE, "--readonly-role", READONLY_ROLE]) == 0
    out = capsys.readouterr().out
    assert f"-> {schema.expected_head()}" in out
    assert f"grants: {APP_ROLE} read/write" in out and "append-only audit_log, consents" in out
    assert cli.main(["migrate", "--app-role", "missing_role_x"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_check_db_role_command(capsys: pytest.CaptureFixture[str], engine: Engine) -> None:
    assert cli.main(["check-db-role"]) == 0
    assert "data access only" in capsys.readouterr().out


def test_worker_stops_cleanly_and_writes_heartbeat(tmp_path: Path, engine: Engine) -> None:
    heartbeat = tmp_path / "heartbeat"
    assert cli.main(["worker", "--interval", "0.01", "--iterations", "2", "--heartbeat-file", str(heartbeat)]) == 0
    assert heartbeat.exists()
    # A container stop sends SIGTERM: the worker finishes its batch and exits instead of looping forever.
    timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM))
    timer.start()
    started = time.monotonic()
    assert cli._worker(0.05, None, heartbeat) == 0
    assert time.monotonic() - started < 5
    assert signal.getsignal(signal.SIGTERM) is not cli._Stop.handle  # previous handler restored


# ------------------------------------------------------------------------------- restore check


def test_backup_manifest_and_restore_check_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], owner_engine: Engine
) -> None:
    monkeypatch.setenv("MIXT_BACKUP_DATABASE_URL", TEST_DATABASE_URL)
    manifest = tmp_path / "manifest.json"
    assert cli.main(["backup-manifest", "--out", str(manifest)]) == 0
    data = json.loads(manifest.read_text())
    assert data["schema_revision"] == schema.expected_head() and data["tables"]["markets"] == 13
    capsys.readouterr()
    assert cli.main(["verify-restore", "--database-url", TEST_DATABASE_URL, "--manifest", str(manifest)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert {c["name"] for c in report["checks"]} >= {
        "schema_revision",
        "schema_matches_manifest",
        "tables_present",
        "integrity_triggers",
        "audit_chain",
        "audit_tip_present",
        "us_not_a_market",
    }


def test_restore_check_detects_a_broken_audit_chain(owner_db: Session) -> None:
    for i in range(3):
        audit.record(owner_db, SYSTEM_ACTOR, "test_event", "test", str(i), {"i": i})
    owner_db.flush()
    conn = owner_db.connection()
    expected = restore_check.manifest(conn)
    assert restore_check.verify_connection(conn, expected).ok
    target = owner_db.execute(text("SELECT max(chain_seq) - 1 FROM audit_log")).scalar_one()
    owner_db.execute(text("SET LOCAL session_replication_role = replica"))
    owner_db.execute(text(f"UPDATE audit_log SET changes = '{{}}' WHERE chain_seq = {target}"))
    owner_db.execute(text("SET LOCAL session_replication_role = origin"))
    report = restore_check.verify_connection(conn, expected)
    failed = {c.name for c in report.checks if not c.ok}
    assert failed == {"audit_chain"}


def test_restore_check_detects_a_backup_missing_recent_entries(owner_db: Session) -> None:
    audit.record(owner_db, SYSTEM_ACTOR, "test_event", "test", "x", {"i": 1})
    owner_db.flush()
    conn = owner_db.connection()
    expected = restore_check.manifest(conn)
    expected["audit"]["last_chain_seq"] += 1000  # the manifest saw an entry the restored copy lacks
    expected["tables"]["markets"] = 99
    report = restore_check.verify_connection(conn, expected)
    assert {c.name for c in report.checks if not c.ok} == {"audit_tip_present"}
    assert report.count_changes["markets"] == {"manifest": 99, "restored": 13}
    expected = restore_check.manifest(conn)
    expected["audit"]["last_hash"] = "00" * 32
    assert {c.name for c in restore_check.verify_connection(conn, expected).checks if not c.ok} == {"audit_tip_present"}


def test_restore_check_detects_a_wrong_schema_and_lost_triggers(
    owner_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = owner_db.connection()
    owner_db.execute(text("DROP TRIGGER trg_markets_reject_excluded_country ON markets"))
    monkeypatch.setattr(schema, "expected_head", lambda: "9999")
    failed = {c.name for c in restore_check.verify_connection(conn).checks if not c.ok}
    assert failed == {"schema_revision", "integrity_triggers"}
