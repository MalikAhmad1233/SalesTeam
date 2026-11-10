"""Single sign-on (IN-23) against a fake OpenID Connect provider with real RSA-signed tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_ACTOR
from mixt.modules.audit.models import AuditLog
from mixt.modules.identity.access import load_access
from mixt.modules.settings import service as settings
from mixt.modules.sso import oidc
from mixt.modules.sso import service as sso
from mixt.modules.sso.models import UserIdentity
from tests.conftest import make_user, next_code

GOOGLE = "https://idp.test/google"
MICROSOFT = "https://idp.test/ms/v2.0"
TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "mixt-client"


class FakeProvider:
    """Discovery, JWKS and token endpoints. Tests choose the claims of the next ID token."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.claims: dict[str, Any] = {}
        self.header: dict[str, Any] = {}
        self.signing_key: Any = self.key
        self.token_requests: list[dict[str, list[str]]] = []
        self.token_status = 200

    def jwk(self) -> dict[str, Any]:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**public, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def id_token(self, issuer: str) -> str:
        now = int(time.time())
        claims = {"iss": issuer, "aud": CLIENT_ID, "iat": now, "exp": now + 300, **self.claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        headers = {"kid": self.kid, **self.header}
        return jwt.encode(claims, self.signing_key, algorithm="RS256", headers=headers)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for issuer in (GOOGLE, MICROSOFT):
            if url == f"{issuer}/.well-known/openid-configuration":
                return httpx.Response(
                    200,
                    json={
                        "issuer": issuer,
                        "authorization_endpoint": f"{issuer}/authorize",
                        "token_endpoint": f"{issuer}/token",
                        "jwks_uri": f"{issuer}/jwks",
                    },
                )
            if url == f"{issuer}/jwks":
                return httpx.Response(200, json={"keys": [self.jwk()]})
            if url == f"{issuer}/token":
                form = parse_qs(request.content.decode())
                self.token_requests.append(form)
                if self.token_status != 200:
                    return httpx.Response(self.token_status, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"id_token": self.id_token(issuer), "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture
def idp(config_env: Any) -> Iterator[FakeProvider]:
    config_env(
        public_base_url="https://testserver",
        sso_google_client_id=CLIENT_ID,
        sso_google_client_secret="google-secret",
        sso_microsoft_client_id=CLIENT_ID,
        sso_microsoft_client_secret="ms-secret",
        sso_microsoft_tenant_id=TENANT,
        sso_issuer_overrides=json.dumps({"google": GOOGLE, "microsoft": MICROSOFT}),
    )
    provider = FakeProvider()
    oidc.set_transport(httpx.MockTransport(provider.handler))
    yield provider
    oidc.set_transport(None)


def _set(db: Session, key: str, value: Any) -> None:
    owner = make_user(db, [("owner", None)])
    settings.change(db, owner.actor, load_access(db, owner.actor), key, value, "safe_default", None)


def _start(client: TestClient, next_path: str = "/customers") -> dict[str, str]:
    response = client.get("/api/v1/auth/sso/start", params={"next": next_path}, follow_redirects=False)
    assert response.status_code == 302, response.text
    assert "mixt_sso_flow" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"] and "Path=/api/v1/auth/sso" in response.headers["set-cookie"]
    query = parse_qs(urlparse(response.headers["location"]).query)
    return {k: v[0] for k, v in query.items()}


def _callback(client: TestClient, **params: str) -> httpx.Response:
    return client.get("/api/v1/auth/sso/callback", params=params, follow_redirects=False)


def _google_claims(params: dict[str, str], email: str, sub: str = "g-123", **extra: Any) -> dict[str, Any]:
    return {"sub": sub, "email": email, "email_verified": True, "nonce": params["nonce"], **extra}


def test_off_by_default(client: TestClient, idp: FakeProvider) -> None:
    assert client.get("/api/v1/auth/sso").json() == {"enabled": False, "provider": None, "label": None}
    response = client.get("/api/v1/auth/sso/start", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login?sso_error=unavailable"


def test_needs_credentials_even_when_selected(client: TestClient, db: Session, config_env: Any) -> None:
    _set(db, "auth.sso", "google")
    config_env(public_base_url="https://testserver")  # no client id / secret
    assert client.get("/api/v1/auth/sso").json()["enabled"] is False


def test_google_sign_in_links_the_account_and_still_asks_for_the_code(
    client: TestClient, db: Session, idp: FakeProvider
) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    assert client.get("/api/v1/auth/sso").json() == {"enabled": True, "provider": "google", "label": "Google"}
    params = _start(client)
    assert params["code_challenge_method"] == "S256" and params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == "https://testserver/api/v1/auth/sso/callback"
    idp.claims = _google_claims(params, user.user.email.upper())

    response = _callback(client, state=params["state"], code="auth-code-1")
    assert response.status_code == 303 and response.headers["location"] == "/mfa"
    # PKCE: the token request carried the verifier matching the challenge we sent.
    form = idp.token_requests[-1]
    verifier = form["code_verifier"][0]
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert digest == params["code_challenge"] and form["client_secret"] == ["google-secret"]

    me = client.get("/api/v1/auth/me").json()
    assert me["email"] == user.user.email and me["mfa_state"] == "required"
    csrf = client.cookies.get("mixt_csrf")
    verified = client.post(
        "/api/v1/auth/mfa/verify", json={"code": next_code(db, user)}, headers={"X-CSRF-Token": csrf}
    )
    assert verified.status_code == 200 and verified.json()["mfa_state"] == "verified"

    link = db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id))
    assert link is not None and link.provider == "google" and link.subject == "g-123"
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == str(user.id))))
    assert {"sso_identity_linked", "login_succeeded"} <= actions


def test_after_linking_the_subject_counts_not_the_email(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    db.add(UserIdentity(user_id=user.id, provider="google", subject="g-stable", email_at_link=user.user.email))
    db.flush()
    params = _start(client)
    idp.claims = _google_claims(params, "renamed@elsewhere.example", sub="g-stable")
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/mfa"
    assert client.get("/api/v1/auth/me").json()["email"] == user.user.email


def test_provider_mfa_accepted_only_when_mixt_says_so(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email, amr=["pwd", "mfa"])
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/mfa"

    _set(db, "auth.sso_satisfies_mfa", True)
    client.cookies.clear()
    params = _start(client, "/pipeline")
    idp.claims = _google_claims(params, user.user.email, amr=["pwd", "mfa"])
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/pipeline"
    assert client.get("/api/v1/auth/me").json()["mfa_state"] == "verified"

    client.cookies.clear()
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email, amr=["pwd"])  # single factor at the provider
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/mfa"


def test_temporary_password_must_still_be_changed(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    _set(db, "auth.sso_satisfies_mfa", True)
    user = make_user(db, must_change_password=True)
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email, amr=["mfa"])
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/password"


def _expect_refusal(response: httpx.Response, code: str) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?sso_error={code}"
    assert "mixt_session" not in response.headers.get("set-cookie", "")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda idp, p, email: idp.claims.update(nonce="replayed-nonce"), "invalid"),
        (lambda idp, p, email: idp.claims.update(aud="another-app"), "invalid"),
        (lambda idp, p, email: idp.claims.update(iss="https://evil.example"), "invalid"),
        (lambda idp, p, email: idp.claims.update(exp=int(time.time()) - 3600), "invalid"),
        (lambda idp, p, email: idp.claims.update(email_verified=False), "invalid"),
        (lambda idp, p, email: idp.claims.update(azp="another-app"), "invalid"),
        (lambda idp, p, email: setattr(idp, "signing_key", idp.other_key), "invalid"),
        (lambda idp, p, email: setattr(idp, "header", {"kid": "unknown"}), "invalid"),
        (lambda idp, p, email: setattr(idp, "token_status", 400), "invalid"),
        (lambda idp, p, email: idp.claims.update(email="stranger@example.com"), "no_account"),
    ],
)
def test_bad_tokens_are_refused(client: TestClient, db: Session, idp: FakeProvider, mutate: Any, code: str) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email)
    mutate(idp, params, user.user.email)
    _expect_refusal(_callback(client, state=params["state"], code="c"), code)
    assert db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id)) is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "sso_login_failed")) is not None


def test_unsigned_tokens_are_refused(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    params = _start(client)
    claims = _google_claims(params, user.user.email)
    unsigned = jwt.encode({**claims, "iss": GOOGLE, "aud": CLIENT_ID, "exp": int(time.time()) + 60}, None, "none")
    idp.id_token = lambda issuer: unsigned  # type: ignore[method-assign]
    _expect_refusal(_callback(client, state=params["state"], code="c"), "invalid")


def test_flow_state_must_match(client: TestClient, db: Session, idp: FakeProvider, app_factory: Any) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email)
    _expect_refusal(_callback(client, state="forged", code="c"), "expired")
    # A different browser (no flow cookie) cannot finish someone else's sign-in.
    _expect_refusal(_callback(app_factory(), state=params["state"], code="c"), "expired")
    # The flow cookie is single-use: it is cleared by the first callback.
    assert "mixt_sso_flow" not in client.cookies


def test_cancelled_at_the_provider(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    params = _start(client)
    _expect_refusal(_callback(client, state=params["state"], error="access_denied"), "cancelled")


def test_suspended_staff_cannot_use_sso(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db, status="suspended")
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email)
    _expect_refusal(_callback(client, state=params["state"], code="c"), "disabled")


def test_allowed_domains(client: TestClient, db: Session, idp: FakeProvider, config_env: Any) -> None:
    _set(db, "auth.sso", "google")
    config_env(sso_allowed_domains='["mixt.example"]')
    user = make_user(db)  # @mixt-test.example
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email)
    _expect_refusal(_callback(client, state=params["state"], code="c"), "domain")


def test_account_already_linked_to_another_google_account(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    user = make_user(db)
    db.add(UserIdentity(user_id=user.id, provider="google", subject="g-original", email_at_link=user.user.email))
    db.flush()
    params = _start(client)
    idp.claims = _google_claims(params, user.user.email, sub="g-impostor")
    _expect_refusal(_callback(client, state=params["state"], code="c"), "invalid")


def test_next_path_cannot_redirect_elsewhere() -> None:
    assert sso.safe_next("//evil.example/") == "/"
    assert sso.safe_next("https://evil.example/") == "/"
    assert sso.safe_next("/\\evil.example") == "/"
    assert sso.safe_next("/customers?tab=open") == "/customers?tab=open"
    assert sso.safe_next(None) == "/"


def test_microsoft_requires_mixts_tenant(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "microsoft")
    user = make_user(db)
    params = _start(client)
    oid = str(uuid.uuid4())
    idp.claims = {"sub": "pairwise", "oid": oid, "tid": TENANT, "preferred_username": user.user.email}
    idp.claims["nonce"] = params["nonce"]
    assert _callback(client, state=params["state"], code="c").headers["location"] == "/mfa"
    link = db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id))
    assert link is not None and link.subject == f"{TENANT}:{oid}"

    client.cookies.clear()
    other = make_user(db)
    params = _start(client)
    idp.claims = {
        "sub": "x",
        "oid": str(uuid.uuid4()),
        "tid": "99999999-2222-3333-4444-555555555555",
        "preferred_username": other.user.email,
        "nonce": params["nonce"],
    }
    _expect_refusal(_callback(client, state=params["state"], code="c"), "invalid")


def test_microsoft_needs_a_real_tenant_id(db: Session, config_env: Any, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "microsoft")
    config_env(sso_microsoft_tenant_id="common")  # any Microsoft account: refused
    assert sso.configured_provider(db) is None


def test_discovery_must_match_the_issuer(db: Session, idp: FakeProvider, config_env: Any) -> None:
    _set(db, "auth.sso", "google")
    config_env(sso_issuer_overrides=json.dumps({"google": "https://idp.test/other"}))
    oidc.clear_cache()
    with pytest.raises(sso.SsoFailure) as info:
        sso.begin(db, "/")
    assert info.value.code == "unavailable"


def test_unreachable_provider(db: Session, idp: FakeProvider) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    _set(db, "auth.sso", "google")
    oidc.set_transport(httpx.MockTransport(boom))
    with pytest.raises(sso.SsoFailure) as info:
        sso.begin(db, "/")
    assert info.value.code == "unavailable" and "unreachable" in info.value.reason


def test_tampered_flow_cookie_is_ignored() -> None:
    assert sso._open("not-base64!") is None
    assert sso._open(base64.urlsafe_b64encode(b'{"k": "test-k1", "c": "AAAA"}').decode()) is None
    stale = sso.Flow("google", "s", "n", "v", "/", int(time.time()) - sso.FLOW_MAX_AGE_SECONDS - 5)
    assert sso._open(sso._seal(stale)) is None
    fresh = sso.Flow("google", "s", "n", "v", "/", int(time.time()))
    assert sso._open(sso._seal(fresh)) == fresh


def test_failed_attempts_are_audited_without_personal_data(client: TestClient, db: Session, idp: FakeProvider) -> None:
    _set(db, "auth.sso", "google")
    params = _start(client)
    idp.claims = _google_claims(params, "stranger@example.com")
    _callback(client, state=params["state"], code="c")
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "sso_login_failed").order_by(AuditLog.chain_seq.desc()))
    assert entry is not None and entry.actor_principal_id == SYSTEM_ACTOR.principal_id
    assert "stranger" not in json.dumps(entry.changes)
