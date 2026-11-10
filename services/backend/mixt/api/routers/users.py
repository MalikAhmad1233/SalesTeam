"""Staff user management."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mixt.api.deps import AuthContext, require
from mixt.core.db import get_session
from mixt.modules.identity import service as identity
from mixt.modules.identity.models import User
from mixt.modules.identity.service import RoleGrant

router = APIRouter(tags=["users"])


class RoleGrantIn(BaseModel):
    role: str
    market_id: uuid.UUID | None = None


class UserCreateIn(BaseModel):
    email: str = Field(max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    temporary_password: str = Field(max_length=256)
    timezone: str = "UTC"
    roles: list[RoleGrantIn] = Field(min_length=1)


class UserStatusIn(BaseModel):
    status: str


class RolesIn(BaseModel):
    roles: list[RoleGrantIn] = Field(min_length=1)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    status: str
    timezone: str
    must_change_password: bool
    last_login_at: datetime | None
    roles: list[RoleGrantIn]


class RoleOut(BaseModel):
    key: str
    name: str
    description: str
    permissions: list[str]


def _out(db: Session, user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        timezone=user.timezone,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        roles=[RoleGrantIn(role=r, market_id=m) for r, m in identity.roles_of(db, user.principal_id)],
    )


def _grants(items: list[RoleGrantIn]) -> list[RoleGrant]:
    return [RoleGrant(role_key=i.role, market_id=i.market_id) for i in items]


@router.get("/users", response_model=list[UserOut])
def list_users(auth: AuthContext = Depends(require("users.read")), db: Session = Depends(get_session)) -> list[UserOut]:
    return [_out(db, u) for u in identity.list_users(db, auth.access)]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreateIn, auth: AuthContext = Depends(require("users.manage")), db: Session = Depends(get_session)
) -> UserOut:
    user = identity.create_user(
        db,
        auth.actor,
        auth.access,
        body.email,
        body.full_name,
        body.temporary_password,
        _grants(body.roles),
        body.timezone,
    )
    return _out(db, user)


@router.patch("/users/{user_id}/status", response_model=UserOut)
def set_status(
    user_id: uuid.UUID,
    body: UserStatusIn,
    auth: AuthContext = Depends(require("users.manage")),
    db: Session = Depends(get_session),
) -> UserOut:
    return _out(db, identity.set_user_status(db, auth.actor, auth.access, user_id, body.status))


@router.post("/users/{user_id}/roles", response_model=UserOut)
def grant_roles(
    user_id: uuid.UUID,
    body: RolesIn,
    auth: AuthContext = Depends(require("users.manage")),
    db: Session = Depends(get_session),
) -> UserOut:
    identity.grant_roles(db, auth.actor, auth.access, user_id, _grants(body.roles))
    return _out(db, identity.get_user(db, auth.access, user_id))


@router.post("/users/{user_id}/roles/revoke", response_model=UserOut)
def revoke_role(
    user_id: uuid.UUID,
    body: RoleGrantIn,
    auth: AuthContext = Depends(require("users.manage")),
    db: Session = Depends(get_session),
) -> UserOut:
    identity.revoke_role(db, auth.actor, auth.access, user_id, RoleGrant(body.role, body.market_id))
    return _out(db, identity.get_user(db, auth.access, user_id))


@router.get("/roles", response_model=list[RoleOut])
def list_roles(auth: AuthContext = Depends(require("users.read")), db: Session = Depends(get_session)) -> list[RoleOut]:
    return [
        RoleOut(key=r.key, name=r.name, description=r.description, permissions=perms)
        for r, perms in identity.list_roles(db, auth.access)
    ]
