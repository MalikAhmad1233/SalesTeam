"""Single sign-on endpoints. These are browser navigations (redirects), not JSON calls: problems
send the person back to the sign-in page with a short error code the page explains."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mixt.api import throttle
from mixt.api.deps import client_ip
from mixt.api.routers.auth import set_session_cookies
from mixt.core.config import get_config
from mixt.core.db import get_session
from mixt.core.logging import get_logger
from mixt.modules.sso import service as sso

router = APIRouter(prefix="/auth/sso", tags=["auth"])
log = get_logger("mixt.sso")
FLOW_COOKIE = "mixt_sso_flow"
FLOW_COOKIE_PATH = "/api/v1/auth/sso"


class SsoInfoOut(BaseModel):
    enabled: bool
    provider: Literal["google", "microsoft"] | None
    label: str | None


def _to_login(code: str) -> RedirectResponse:
    return RedirectResponse(f"/login?sso_error={code}", status_code=303)


def _clear_flow_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH, secure=get_config().cookie_secure, samesite="lax")


@router.get("", response_model=SsoInfoOut)
def sso_info(db: Session = Depends(get_session, scope="function")) -> SsoInfoOut:
    found = sso.info(db)
    provider: Literal["google", "microsoft"] | None = None
    if found.provider == "google":
        provider = "google"
    elif found.provider == "microsoft":
        provider = "microsoft"
    return SsoInfoOut(enabled=found.enabled, provider=provider, label=found.label)


@router.get("/start", response_class=RedirectResponse, status_code=302)
def sso_start(
    request: Request, next: str | None = None, db: Session = Depends(get_session, scope="function")
) -> RedirectResponse:
    if not throttle.check("sso_per_ip", client_ip(request)).allowed:
        return _to_login("rate_limited")
    try:
        begun = sso.begin(db, next)
    except sso.SsoFailure as exc:
        log.info("sso_start_refused", code=exc.code, reason=exc.reason)
        return _to_login(exc.code)
    response = RedirectResponse(begun.redirect_url, status_code=302)
    response.set_cookie(
        FLOW_COOKIE,
        begun.flow_cookie,
        max_age=sso.FLOW_MAX_AGE_SECONDS,
        httponly=True,
        secure=get_config().cookie_secure,
        samesite="lax",
        path=FLOW_COOKIE_PATH,
    )
    return response


@router.get("/callback", response_class=RedirectResponse, status_code=303)
def sso_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_session, scope="function"),
) -> RedirectResponse:
    ip = client_ip(request)
    if not throttle.check("sso_per_ip", ip).allowed:
        response = _to_login("rate_limited")
        _clear_flow_cookie(response)
        return response
    try:
        completed = sso.complete(
            db, request.cookies.get(FLOW_COOKIE), state, code, error, ip, request.headers.get("user-agent")
        )
    except sso.SsoFailure as exc:
        # Returning normally commits the transaction, which keeps the audit entry of the failure.
        log.info("sso_refused", code=exc.code, reason=exc.reason)
        response = _to_login(exc.code)
    else:
        outcome = completed.outcome
        if outcome.issued is None or outcome.user is None:  # not reachable: ok=True sets both
            return _to_login("invalid")
        if outcome.mfa_state != "verified":
            target = "/mfa"
        elif outcome.user.must_change_password:
            target = "/password"
        else:
            target = completed.next_path
        response = RedirectResponse(target, status_code=303)
        set_session_cookies(response, outcome.issued)
    _clear_flow_cookie(response)
    return response
