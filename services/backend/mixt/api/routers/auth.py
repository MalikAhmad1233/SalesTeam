"""Sign-in, two-step verification, password change and sign-out."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api import throttle
from mixt.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AuthContext,
    client_ip,
    mfa_auth,
    session_auth,
)
from mixt.core.config import get_config
from mixt.core.db import get_session
from mixt.core.errors import AuthenticationRequired
from mixt.modules.identity import service as identity
from mixt.modules.identity.service import IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class MeRoleOut(BaseModel):
    role: str
    market_id: uuid.UUID | None


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    timezone: str
    mfa_state: Literal["verified", "required", "enrollment_required"]
    must_change_password: bool
    roles: list[MeRoleOut]
    permissions: list[str]


class SessionOut(BaseModel):
    mfa_state: Literal["verified", "required", "enrollment_required"]
    must_change_password: bool
    csrf_token: str


class TotpSetupOut(BaseModel):
    secret: str
    provisioning_uri: str


def set_session_cookies(response: Response, issued: IssuedSession) -> None:
    config = get_config()
    max_age = config.session_absolute_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=max_age,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    config = get_config()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=config.cookie_secure, samesite="lax")


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_session)) -> SessionOut:
    ip = client_ip(request)
    throttle.enforce("login_per_ip", ip)
    throttle.enforce("login_per_account", body.email.strip().lower())
    outcome = identity.authenticate(db, body.email, body.password, ip, request.headers.get("user-agent"))
    if not outcome.ok or outcome.issued is None or outcome.user is None or outcome.mfa_state is None:
        db.commit()  # keep failed-attempt counters and audit entries
        raise AuthenticationRequired(
            "INVALID_CREDENTIALS", "Email or password is incorrect, or the account is temporarily locked."
        )
    set_session_cookies(response, outcome.issued)
    return SessionOut(
        mfa_state=outcome.mfa_state,
        must_change_password=outcome.user.must_change_password,
        csrf_token=outcome.issued.csrf_token,
    )


@router.post("/logout", status_code=204)
def logout(response: Response, auth: AuthContext = Depends(session_auth), db: Session = Depends(get_session)) -> None:
    identity.logout(db, auth.actor, auth.session)
    _clear_cookies(response)


@router.get("/me", response_model=MeOut)
def me(auth: AuthContext = Depends(session_auth), db: Session = Depends(get_session)) -> MeOut:
    return MeOut(
        id=auth.user.id,
        email=auth.user.email,
        full_name=auth.user.full_name,
        timezone=auth.user.timezone,
        mfa_state=identity.mfa_state_for(db, auth.user, auth.session),
        must_change_password=auth.user.must_change_password,
        roles=[MeRoleOut(role=r, market_id=m) for r, m in identity.roles_of(db, auth.user.principal_id)],
        permissions=sorted(auth.access.grants),
    )


@router.post("/mfa/totp/setup", response_model=TotpSetupOut)
def totp_setup(auth: AuthContext = Depends(session_auth), db: Session = Depends(get_session)) -> TotpSetupOut:
    setup = identity.start_totp_enrollment(db, auth.actor, auth.user)
    return TotpSetupOut(secret=setup.secret, provisioning_uri=setup.provisioning_uri)


def _finish_mfa(db: Session, response: Response, auth: AuthContext, issued: IssuedSession | None) -> SessionOut:
    if issued is None:
        db.commit()  # keep failed-attempt counters and audit entries
        raise AuthenticationRequired("INVALID_MFA_CODE", "That code is not valid. Use the current code from your app.")
    set_session_cookies(response, issued)
    return SessionOut(
        mfa_state="verified", must_change_password=auth.user.must_change_password, csrf_token=issued.csrf_token
    )


@router.post("/mfa/totp/confirm", response_model=SessionOut)
def totp_confirm(
    body: CodeIn, response: Response, auth: AuthContext = Depends(session_auth), db: Session = Depends(get_session)
) -> SessionOut:
    throttle.enforce("mfa_per_session", str(auth.session.id))
    issued = identity.confirm_totp_enrollment(db, auth.actor, auth.user, auth.session, body.code)
    return _finish_mfa(db, response, auth, issued)


@router.post("/mfa/verify", response_model=SessionOut)
def mfa_verify(
    body: CodeIn, response: Response, auth: AuthContext = Depends(session_auth), db: Session = Depends(get_session)
) -> SessionOut:
    throttle.enforce("mfa_per_session", str(auth.session.id))
    issued = identity.verify_mfa(db, auth.actor, auth.user, auth.session, body.code)
    return _finish_mfa(db, response, auth, issued)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeIn, auth: AuthContext = Depends(mfa_auth), db: Session = Depends(get_session)
) -> None:
    throttle.enforce("password_per_user", str(auth.user.id))
    identity.change_password(db, auth.actor, auth.user, auth.session, body.current_password, body.new_password)
