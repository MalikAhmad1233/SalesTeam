"""Request authentication and authorisation dependencies.

Order of checks for a protected request:
1. valid, unexpired session cookie;
2. CSRF header on any state-changing request;
3. MFA completed (unless the route is part of MFA set-up);
4. password change completed (unless the route is the password change itself).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from mixt.api import throttle
from mixt.api.net import resolve_client_ip
from mixt.core.config import get_config
from mixt.core.context import Actor
from mixt.core.db import get_session
from mixt.core.errors import AuthenticationRequired, PermissionDenied, PreconditionRequired
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access, load_access
from mixt.modules.identity.models import User, UserSession

SESSION_COOKIE = "mixt_session"
CSRF_COOKIE = "mixt_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession
    actor: Actor
    access: Access


def client_ip(request: Request) -> str | None:
    """The client's address (behind trusted proxies only), if it is a valid IP."""
    return resolve_client_ip(request, get_config().trusted_proxies)


def _base_auth(request: Request, db: Session) -> AuthContext:
    resolved = identity.resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if resolved is None:
        raise AuthenticationRequired("NOT_AUTHENTICATED", "Sign in to continue.")
    throttle.enforce("api_per_user", str(resolved.user.id))
    if request.method not in _SAFE_METHODS and not identity.csrf_matches(
        resolved.session, request.headers.get(CSRF_HEADER)
    ):
        raise PermissionDenied("CSRF_TOKEN_INVALID", "Missing or invalid CSRF token.")
    actor = identity.user_actor(
        resolved.user,
        client_ip(request),
        request.headers.get("user-agent"),
        getattr(request.state, "correlation_id", None),
    )
    return AuthContext(resolved.user, resolved.session, actor, load_access(db, actor))


def session_auth(request: Request, db: Session = Depends(get_session, scope="function")) -> AuthContext:
    """Authenticated session, MFA possibly still pending (MFA and 'me' routes only)."""
    return _base_auth(request, db)


def mfa_auth(request: Request, db: Session = Depends(get_session, scope="function")) -> AuthContext:
    """Authenticated and MFA complete; password change may still be pending."""
    auth = _base_auth(request, db)
    if not auth.session.mfa_verified:
        state = identity.mfa_state_for(db, auth.user, auth.session)
        code = "MFA_ENROLLMENT_REQUIRED" if state == "enrollment_required" else "MFA_REQUIRED"
        raise AuthenticationRequired(code, "Complete two-step verification first.")
    return auth


def current_auth(auth: AuthContext = Depends(mfa_auth)) -> AuthContext:
    """Fully signed-in user: MFA done and no pending password change."""
    if auth.user.must_change_password:
        raise PermissionDenied("PASSWORD_CHANGE_REQUIRED", "Change your temporary password first.")
    return auth


def require(permission: str) -> Callable[[AuthContext], AuthContext]:
    def dependency(auth: AuthContext = Depends(current_auth)) -> AuthContext:
        auth.access.require_somewhere(permission)
        return auth

    return dependency


def if_match_version(if_match: str | None = Header(default=None, alias="If-Match")) -> int:
    """Optimistic concurrency: clients send the version they edited as `If-Match: "3"`."""
    if if_match is None:
        raise PreconditionRequired("VERSION_REQUIRED", 'Send the record version you edited, e.g. If-Match: "3".')
    try:
        return int(if_match.strip().removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise PreconditionRequired("VERSION_REQUIRED", 'If-Match must be a version number, e.g. "3".') from exc
