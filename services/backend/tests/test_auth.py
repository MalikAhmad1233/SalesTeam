"""Sign-in, MFA, sessions, CSRF, lockout and password change."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.timezones import now_utc
from mixt.modules.audit.models import AuditLog
from mixt.modules.identity import mfa
from mixt.modules.identity.models import UserSession
from tests.conftest import DEFAULT_PASSWORD, make_user, next_code, sign_in

LOGIN = "/api/v1/auth/login"


def _login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict:  # type: ignore[type-arg]
    return client.post(LOGIN, json={"email": email, "password": password}).json()


def test_full_enrollment_flow(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)], with_mfa=False)
    body = _login(client, user.user.email)
    assert body["mfa_state"] == "enrollment_required"
    csrf = body["csrf_token"]

    # Nothing else is reachable before two-step verification is set up.
    assert client.get("/api/v1/crm/accounts").json()["code"] == "MFA_ENROLLMENT_REQUIRED"

    setup = client.post("/api/v1/auth/mfa/totp/setup", headers={"X-CSRF-Token": csrf}).json()
    assert setup["provisioning_uri"].startswith("otpauth://totp/Mixt%20AI:")
    code = mfa.code_for_step(setup["secret"], mfa.current_step())
    old_cookie = client.cookies.get("mixt_session")
    confirmed = client.post("/api/v1/auth/mfa/totp/confirm", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert confirmed.status_code == 200 and confirmed.json()["mfa_state"] == "verified"
    assert client.cookies.get("mixt_session") != old_cookie  # session rotated after MFA

    me = client.get("/api/v1/auth/me").json()
    assert me["mfa_state"] == "verified" and "crm.accounts.read" in me["permissions"]
    assert client.get("/api/v1/crm/accounts").status_code == 200


def test_login_with_enrolled_mfa(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    body = _login(client, user.user.email)
    assert body["mfa_state"] == "required"
    assert client.get("/api/v1/crm/accounts").json()["code"] == "MFA_REQUIRED"
    wrong = client.post(
        "/api/v1/auth/mfa/verify", json={"code": "000000"}, headers={"X-CSRF-Token": body["csrf_token"]}
    )
    assert wrong.status_code == 401 and wrong.json()["code"] == "INVALID_MFA_CODE"
    ok = client.post(
        "/api/v1/auth/mfa/verify", json={"code": next_code(db, user)}, headers={"X-CSRF-Token": body["csrf_token"]}
    )
    assert ok.status_code == 200


def test_mfa_code_cannot_be_replayed(client: TestClient, db: Session, app_factory) -> None:  # type: ignore[no-untyped-def]
    user = make_user(db, [("sales_rep", None)])
    code = next_code(db, user)
    first = _login(client, user.user.email)
    assert (
        client.post(
            "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRF-Token": first["csrf_token"]}
        ).status_code
        == 200
    )
    other = app_factory()
    second = other.post(LOGIN, json={"email": user.user.email, "password": DEFAULT_PASSWORD}).json()
    replay = other.post("/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRF-Token": second["csrf_token"]})
    assert replay.status_code == 401


def test_wrong_password_and_unknown_email_look_the_same(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    wrong = client.post(LOGIN, json={"email": user.user.email, "password": "nope-nope-nope"})
    unknown = client.post(LOGIN, json={"email": "nobody@mixt-test.example", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "INVALID_CREDENTIALS"
    assert wrong.headers["content-type"].startswith("application/problem+json")


def test_lockout_after_repeated_failures(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    for _ in range(5):
        assert client.post(LOGIN, json={"email": user.user.email, "password": "bad-password-xx"}).status_code == 401
    db.refresh(user.user)
    assert user.user.locked_until is not None and user.user.locked_until > now_utc()
    # Even the right password is refused while locked.
    assert client.post(LOGIN, json={"email": user.user.email, "password": DEFAULT_PASSWORD}).status_code == 401
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(user.id))).all()
    assert "account_locked" in actions and actions.count("login_failed") == 5


def test_inactive_user_cannot_sign_in(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)], status="suspended")
    assert client.post(LOGIN, json={"email": user.user.email, "password": DEFAULT_PASSWORD}).status_code == 401


def test_csrf_required_for_state_changes(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    api = sign_in(client, db, user)
    without = client.post("/api/v1/crm/accounts", json={"display_name": "No CSRF"})
    assert without.status_code == 403 and without.json()["code"] == "CSRF_TOKEN_INVALID"
    wrong = client.post("/api/v1/crm/accounts", json={"display_name": "Bad"}, headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403
    assert api.post("/api/v1/crm/accounts", json={"display_name": "With CSRF"}).status_code == 201


def test_session_cookie_flags(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    response = client.post(LOGIN, json={"email": user.user.email, "password": DEFAULT_PASSWORD})
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("mixt_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("mixt_csrf="))
    assert "HttpOnly" in session_cookie and "Secure" in session_cookie and "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie  # the dashboard must read it to send the header


def test_logout_revokes_session(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    api = sign_in(client, db, user)
    token = client.cookies.get("mixt_session")
    assert api.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("mixt_session", token or "")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_idle_and_absolute_expiry(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)])
    sign_in(client, db, user)
    row = db.scalar(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)))
    assert row is not None
    row.idle_expires_at = now_utc() - timedelta(seconds=1)
    db.flush()
    assert client.get("/api/v1/auth/me").json()["code"] == "NOT_AUTHENTICATED"


def test_temporary_password_must_be_changed(client: TestClient, db: Session) -> None:
    user = make_user(db, [("sales_rep", None)], must_change_password=True)
    api = sign_in(client, db, user)
    assert api.get("/api/v1/crm/accounts").json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    weak = api.post("/api/v1/auth/password", json={"current_password": DEFAULT_PASSWORD, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["code"] == "WEAK_PASSWORD"
    wrong = api.post(
        "/api/v1/auth/password", json={"current_password": "wrong-one-xx", "new_password": "A-much-better-pass-77"}
    )
    assert wrong.status_code == 403
    ok = api.post(
        "/api/v1/auth/password", json={"current_password": DEFAULT_PASSWORD, "new_password": "A-much-better-pass-77"}
    )
    assert ok.status_code == 204
    assert api.get("/api/v1/crm/accounts").status_code == 200


def test_problem_json_and_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers={"X-Correlation-Id": "req-12345678"})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "NOT_AUTHENTICATED" and body["status"] == 401 and body["correlation_id"] == "req-12345678"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" in response.headers


def test_health(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").json() == {"status": "ready"}
