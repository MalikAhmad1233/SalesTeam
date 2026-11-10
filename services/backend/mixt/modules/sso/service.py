"""Staff single sign-on (IN-23, setting ``auth.sso``, open question Q-TECH-01).

Rules:
* **Off by default.** It works only when the Owner selects a provider in ``auth.sso`` *and* the
  deployment holds that provider's client credentials and public URL.
* **No self-registration.** Single sign-on signs in existing, active staff accounts only. Roles are
  still granted by an administrator. The first sign-in links the provider account to the staff
  account with the same email address; afterwards the provider's stable subject is used, never the
  email again.
* **Two-step verification still applies** unless ``auth.sso_satisfies_mfa`` is switched on *and*
  the provider says the sign-in used multiple factors.
* Microsoft is accepted only from Mixt's own tenant (a tenant id, never ``common``), which closes
  the "any Microsoft account with a matching email" hole.
* Optional allow-list of email domains (``MIXT_SSO_ALLOWED_DOMAINS``).
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core import crypto
from mixt.core.config import get_config
from mixt.core.context import SYSTEM_ACTOR
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.identity import service as identity
from mixt.modules.settings import service as settings
from mixt.modules.sso import oidc
from mixt.modules.sso.models import UserIdentity

FLOW_MAX_AGE_SECONDS = 600
CALLBACK_PATH = "/api/v1/auth/sso/callback"
_FLOW_AAD = "sso-flow:v1"
_TENANT_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SAFE_NEXT = re.compile(r"^/(?!/)[A-Za-z0-9/_\-?=&.%]*$")
LABELS = {"google": "Google", "microsoft": "Microsoft"}


class SsoFailure(Exception):
    """Sign-in refused. ``code`` is shown to the person (as a friendly message); ``reason`` is logged."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Flow:
    provider: str
    state: str
    nonce: str
    verifier: str
    next_path: str
    created_at: int


@dataclass(frozen=True)
class SsoInfo:
    enabled: bool
    provider: str | None
    label: str | None


@dataclass(frozen=True)
class Begun:
    redirect_url: str
    flow_cookie: str


@dataclass(frozen=True)
class Completed:
    outcome: identity.LoginOutcome
    next_path: str


def configured_provider(db: Session) -> oidc.Provider | None:
    """The provider to use, or None when single sign-on is off or not fully configured."""
    choice = settings.get_value(db, "auth.sso")
    config = get_config()
    if choice == "off" or not config.public_base_url:
        return None
    override = config.sso_issuer_overrides.get(choice)
    if choice == "google" and config.sso_google_client_id and config.sso_google_client_secret:
        return oidc.Provider(
            "google",
            LABELS["google"],
            override or "https://accounts.google.com",
            config.sso_google_client_id,
            config.sso_google_client_secret.get_secret_value(),
        )
    tenant = config.sso_microsoft_tenant_id
    if (
        choice == "microsoft"
        and config.sso_microsoft_client_id
        and config.sso_microsoft_client_secret
        and tenant
        and _TENANT_RE.match(tenant)
    ):
        return oidc.Provider(
            "microsoft",
            LABELS["microsoft"],
            override or f"https://login.microsoftonline.com/{tenant}/v2.0",
            config.sso_microsoft_client_id,
            config.sso_microsoft_client_secret.get_secret_value(),
            tenant_id=tenant.lower(),
        )
    return None


def info(db: Session) -> SsoInfo:
    provider = configured_provider(db)
    return SsoInfo(provider is not None, provider.key if provider else None, provider.label if provider else None)


def redirect_uri() -> str:
    return f"{get_config().public_base_url}{CALLBACK_PATH}"


def safe_next(value: str | None) -> str:
    """Only same-site relative paths, so the sign-in cannot be used as an open redirect."""
    if value and len(value) <= 512 and _SAFE_NEXT.match(value):
        return value
    return "/"


def _seal(flow: Flow) -> str:
    sealed = crypto.encrypt_text(json.dumps(asdict(flow)), _FLOW_AAD)
    envelope = json.dumps({"k": sealed.key_id, "c": base64.b64encode(sealed.ciphertext).decode("ascii")})
    return base64.urlsafe_b64encode(envelope.encode("utf-8")).decode("ascii")


def _open(value: str | None) -> Flow | None:
    if not value or len(value) > 4096:
        return None
    try:
        envelope = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        sealed = crypto.EncryptedValue(ciphertext=base64.b64decode(envelope["c"]), key_id=str(envelope["k"]))
        flow = Flow(**json.loads(crypto.decrypt_text(sealed, _FLOW_AAD)))
    except (ValueError, KeyError, TypeError, crypto.DecryptionError):
        return None
    if time.time() - flow.created_at > FLOW_MAX_AGE_SECONDS:
        return None
    return flow


def begin(db: Session, next_path: str | None) -> Begun:
    provider = configured_provider(db)
    if provider is None:
        raise SsoFailure("unavailable", "single sign-on is off or not configured")
    pkce = oidc.Pkce.new()
    flow = Flow(
        provider=provider.key,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        verifier=pkce.verifier,
        next_path=safe_next(next_path),
        created_at=int(time.time()),
    )
    try:
        url = oidc.authorization_url(provider, redirect_uri(), flow.state, flow.nonce, pkce)
    except oidc.OidcError as exc:
        raise SsoFailure("unavailable", exc.reason) from exc
    return Begun(url, _seal(flow))


def _email_from(provider: oidc.Provider, claims: dict[str, Any]) -> str:
    if provider.key == "google":
        if claims.get("email_verified") is not True or not claims.get("email"):
            raise SsoFailure("invalid", "Google did not confirm the email address")
        return str(claims["email"])
    if str(claims.get("tid", "")).lower() != provider.tenant_id:
        raise SsoFailure("invalid", "Microsoft account from a different organisation (tenant)")
    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        raise SsoFailure("invalid", "Microsoft did not provide an email address")
    return str(email)


def _subject(provider: oidc.Provider, claims: dict[str, Any]) -> str:
    if provider.key == "microsoft":
        oid = claims.get("oid")
        if not oid:
            raise SsoFailure("invalid", "Microsoft token has no object id")
        return f"{provider.tenant_id}:{oid}"
    return str(claims["sub"])


def _domain_allowed(email: str) -> bool:
    allowed = get_config().sso_allowed_domains
    return not allowed or email.rsplit("@", 1)[-1].lower() in allowed


def _fail(db: Session, provider: str, reason: str, user_id: uuid.UUID | None = None) -> None:
    audit.record(db, SYSTEM_ACTOR, "sso_login_failed", "user", user_id, {"provider": provider, "reason": reason})


def complete(
    db: Session,
    flow_cookie: str | None,
    state: str | None,
    code: str | None,
    error: str | None,
    ip: str | None,
    user_agent: str | None,
) -> Completed:
    """Finish the provider round trip. Raises :class:`SsoFailure`; the caller commits either way."""
    flow = _open(flow_cookie)
    if flow is None or not state or not secrets.compare_digest(flow.state, state):
        raise SsoFailure("expired", "sign-in session missing, expired or state mismatch")
    provider = configured_provider(db)
    if provider is None or provider.key != flow.provider:
        raise SsoFailure("unavailable", "single sign-on was switched off or changed during sign-in")
    if error:
        raise SsoFailure("cancelled", f"provider returned error {error[:40]}")
    if not code:
        raise SsoFailure("invalid", "no authorization code")
    try:
        id_token = oidc.exchange_code(provider, code, redirect_uri(), flow.verifier)
        claims = oidc.validate_id_token(provider, id_token, flow.nonce)
    except oidc.OidcError as exc:
        _fail(db, provider.key, exc.reason)
        raise SsoFailure("invalid", exc.reason) from exc
    try:
        email = _email_from(provider, claims)
        subject = _subject(provider, claims)
    except SsoFailure as exc:
        _fail(db, provider.key, exc.reason)
        raise
    if not _domain_allowed(email):
        _fail(db, provider.key, "email domain not allowed")
        raise SsoFailure("domain", "email domain not allowed")

    link = db.scalar(select(UserIdentity).where(UserIdentity.provider == provider.key, UserIdentity.subject == subject))
    if link is not None:
        account = identity.find_account(db, link.user_id)
    else:
        account = identity.find_account_by_email(db, email)
        if account is None:
            _fail(db, provider.key, "no staff account with this email")
            raise SsoFailure("no_account", "no staff account with this email")
        existing = db.scalar(
            select(UserIdentity).where(UserIdentity.user_id == account.user_id, UserIdentity.provider == provider.key)
        )
        if existing is not None:
            # The staff account is already linked to a different provider account.
            _fail(db, provider.key, "account already linked to another provider identity", account.user_id)
            raise SsoFailure("invalid", "account already linked to another provider identity")
        if account.active:
            link = UserIdentity(user_id=account.user_id, provider=provider.key, subject=subject, email_at_link=email)
            db.add(link)
            db.flush()
            audit.record(db, SYSTEM_ACTOR, "sso_identity_linked", "user", account.user_id, {"provider": provider.key})
    if account is None or not account.active:
        _fail(db, provider.key, "account not active", account.user_id if account else None)
        raise SsoFailure("disabled", "account not active")

    amr = claims.get("amr") or []
    provider_mfa = isinstance(amr, list) and "mfa" in amr
    accept_provider_mfa = bool(settings.get_value(db, "auth.sso_satisfies_mfa"))
    outcome = identity.start_external_session(
        db, account.user_id, f"sso:{provider.key}", provider_mfa and accept_provider_mfa, ip, user_agent
    )
    if not outcome.ok:
        raise SsoFailure("disabled", "account not active")
    if link is not None:
        link.last_login_at = now_utc()
    return Completed(outcome, flow.next_path)
