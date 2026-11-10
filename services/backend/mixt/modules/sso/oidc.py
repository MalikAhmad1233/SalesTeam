"""Minimal, strict OpenID Connect client for staff single sign-on (IN-23).

Only the authorization-code flow with PKCE (S256), ``state`` and ``nonce`` is supported. ID tokens
must be RS256-signed by a key from the provider's published JWKS, issued by the configured issuer,
addressed to our client id, unexpired and carry the nonce we sent. Nothing else is accepted.

Discovery documents and key sets are cached for an hour; an unknown key id triggers at most one
refresh per minute (providers rotate keys).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

ALLOWED_ALGORITHMS = ["RS256"]
CACHE_SECONDS = 3600
KEY_REFRESH_MIN_SECONDS = 60
LEEWAY_SECONDS = 60
TIMEOUT_SECONDS = 5.0


class OidcError(Exception):
    """The provider answered wrongly or a token failed validation. ``reason`` is safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Provider:
    key: str  # 'google' | 'microsoft'
    label: str
    issuer: str
    client_id: str
    client_secret: str
    tenant_id: str | None = None


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str

    @classmethod
    def new(cls) -> Pkce:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return cls(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"))


_transport: httpx.BaseTransport | None = None
_cache: dict[str, tuple[float, Any]] = {}
_last_key_refresh: dict[str, float] = {}
_lock = threading.Lock()


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route provider HTTP calls to a fake identity provider."""
    global _transport  # noqa: PLW0603
    _transport = transport
    clear_cache()


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _last_key_refresh.clear()


def _client() -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=TIMEOUT_SECONDS, follow_redirects=False)


def _get_json(url: str, *, force: bool = False) -> Any:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(url)
        if cached and not force and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    try:
        with _client() as client:
            response = client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OidcError(f"provider unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise OidcError(f"provider returned HTTP {response.status_code} for metadata")
    try:
        data = response.json()
    except ValueError as exc:
        raise OidcError("provider metadata is not JSON") from exc
    with _lock:
        _cache[url] = (now, data)
    return data


def discovery(provider: Provider) -> dict[str, Any]:
    data = _get_json(provider.issuer.rstrip("/") + "/.well-known/openid-configuration")
    if not isinstance(data, dict) or data.get("issuer") != provider.issuer:
        raise OidcError("discovery document issuer does not match the configured issuer")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not str(data.get(field, "")).startswith("https://"):
            raise OidcError(f"discovery document has no https {field}")
    return data


def authorization_url(provider: Provider, redirect_uri: str, state: str, nonce: str, pkce: Pkce) -> str:
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{discovery(provider)['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(provider: Provider, code: str, redirect_uri: str, verifier: str) -> str:
    """Swap the authorization code for tokens; returns the raw ID token."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": verifier,
    }
    try:
        with _client() as client:
            response = client.post(discovery(provider)["token_endpoint"], data=form)
    except httpx.HTTPError as exc:
        raise OidcError(f"token endpoint unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise OidcError(f"token endpoint returned HTTP {response.status_code}")
    try:
        id_token = response.json().get("id_token")
    except (ValueError, AttributeError) as exc:
        raise OidcError("token response is not JSON") from exc
    if not isinstance(id_token, str) or not id_token:
        raise OidcError("token response has no id_token")
    return id_token


def _signing_key(provider: Provider, kid: str) -> jwt.PyJWK:
    jwks_uri = discovery(provider)["jwks_uri"]
    for attempt in range(2):
        keys = _get_json(jwks_uri, force=attempt == 1)
        for entry in keys.get("keys", []) if isinstance(keys, dict) else []:
            if entry.get("kid") == kid and entry.get("kty") == "RSA" and entry.get("use", "sig") == "sig":
                return jwt.PyJWK(entry)
        now = time.monotonic()
        with _lock:
            if now - _last_key_refresh.get(jwks_uri, 0.0) < KEY_REFRESH_MIN_SECONDS:
                break
            _last_key_refresh[jwks_uri] = now
    raise OidcError("ID token signed with an unknown key")


def validate_id_token(provider: Provider, id_token: str, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OidcError("ID token is malformed") from exc
    if header.get("alg") not in ALLOWED_ALGORITHMS:
        raise OidcError("ID token uses an algorithm that is not allowed")
    key = _signing_key(provider, str(header.get("kid", "")))
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key=key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=provider.client_id,
            issuer=provider.issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OidcError("ID token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise OidcError("ID token is for a different application") from exc
    except jwt.InvalidIssuerError as exc:
        raise OidcError("ID token comes from a different issuer") from exc
    except jwt.PyJWTError as exc:
        raise OidcError(f"ID token rejected: {type(exc).__name__}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("ID token nonce does not match")
    azp = claims.get("azp")
    if azp is not None and azp != provider.client_id:
        raise OidcError("ID token was issued to a different client")
    return claims
