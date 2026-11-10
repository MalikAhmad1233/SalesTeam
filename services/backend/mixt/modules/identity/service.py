"""Sign-in, MFA, sessions and staff user management."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from mixt.core import crypto
from mixt.core.config import get_config
from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.ids import uuid7
from mixt.core.normalize import normalize_email
from mixt.core.timezones import InvalidTimezone, now_utc, validate_timezone
from mixt.modules.audit import service as audit
from mixt.modules.identity import mfa, passwords
from mixt.modules.identity.access import Access
from mixt.modules.identity.models import (
    Principal,
    PrincipalRole,
    Role,
    RolePermission,
    User,
    UserMfaFactor,
    UserSession,
)

MfaState = Literal["verified", "required", "enrollment_required"]
_TOUCH_INTERVAL = timedelta(seconds=60)


def _hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _factor_aad(factor_id: uuid.UUID) -> str:
    return f"user_mfa_factors:secret:{factor_id}"


def user_actor(
    user: User, ip: str | None = None, user_agent: str | None = None, correlation_id: str | None = None
) -> Actor:
    return Actor(
        principal_id=user.principal_id,
        kind="user",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )


# --------------------------------------------------------------------------- sessions


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    token: str
    csrf_token: str


def _issue_session(
    db: Session, user: User, mfa_verified: bool, ip: str | None, user_agent: str | None
) -> IssuedSession:
    config = get_config()
    now = now_utc()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    row = UserSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        csrf_hash=_hash_token(csrf),
        mfa_verified=mfa_verified,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=config.session_idle_minutes),
        absolute_expires_at=now + timedelta(hours=config.session_absolute_hours),
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(row)
    db.flush()
    return IssuedSession(row, token, csrf)


def _rotate(db: Session, current: UserSession, user: User, mfa_verified: bool) -> IssuedSession:
    """Replace the session after a privilege change (MFA) to prevent session fixation."""
    current.revoked_at = now_utc()
    return _issue_session(db, user, mfa_verified, current.ip, current.user_agent)


@dataclass(frozen=True)
class ResolvedSession:
    session: UserSession
    user: User


def resolve_session(db: Session, token: str | None) -> ResolvedSession | None:
    if not token:
        return None
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    now = now_utc()
    if row is None or row.revoked_at is not None or row.idle_expires_at <= now or row.absolute_expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if now - row.last_seen_at >= _TOUCH_INTERVAL:
        row.last_seen_at = now
        row.idle_expires_at = min(now + timedelta(minutes=get_config().session_idle_minutes), row.absolute_expires_at)
    return ResolvedSession(row, user)


def csrf_matches(row: UserSession, csrf_token: str | None) -> bool:
    return bool(csrf_token) and hmac.compare_digest(row.csrf_hash, _hash_token(csrf_token or ""))


def logout(db: Session, actor: Actor, row: UserSession) -> None:
    row.revoked_at = now_utc()
    audit.record(db, actor, "logout", "user_session", row.id)


def revoke_all_sessions(db: Session, user_id: uuid.UUID, except_session_id: uuid.UUID | None = None) -> None:
    query = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id is not None:
        query = query.where(UserSession.id != except_session_id)
    db.execute(query.values(revoked_at=now_utc()))


# --------------------------------------------------------------------------- login


@dataclass(frozen=True)
class LoginOutcome:
    ok: bool
    issued: IssuedSession | None = None
    user: User | None = None
    mfa_state: MfaState | None = None


def _confirmed_factor(db: Session, user_id: uuid.UUID) -> UserMfaFactor | None:
    return db.scalar(
        select(UserMfaFactor).where(UserMfaFactor.user_id == user_id, UserMfaFactor.confirmed_at.is_not(None))
    )


def _register_failure(db: Session, user: User, ip: str | None, user_agent: str | None, reason: str) -> None:
    config = get_config()
    user.failed_login_count += 1
    actor = user_actor(user, ip, user_agent)
    audit.record(db, actor, "login_failed", "user", user.id, {"reason": reason})
    if user.failed_login_count >= config.login_max_failures:
        user.locked_until = now_utc() + timedelta(minutes=config.login_lockout_minutes)
        user.failed_login_count = 0
        revoke_all_sessions(db, user.id)
        audit.record(db, actor, "account_locked", "user", user.id, {"minutes": config.login_lockout_minutes})


def authenticate(db: Session, email: str, password: str, ip: str | None, user_agent: str | None) -> LoginOutcome:
    """Check credentials. On failure the caller must COMMIT (to persist counters) and then reply 401."""
    try:
        normalized = normalize_email(email)
    except ValidationFailed:
        passwords.burn_time(password)
        return LoginOutcome(ok=False)
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        passwords.burn_time(password)
        return LoginOutcome(ok=False)
    now = now_utc()
    if user.status != "active" or (user.locked_until is not None and user.locked_until > now):
        passwords.burn_time(password)
        return LoginOutcome(ok=False)
    if not passwords.verify_password(user.password_hash, password):
        _register_failure(db, user, ip, user_agent, "bad_password")
        return LoginOutcome(ok=False)

    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    factor = _confirmed_factor(db, user.id)
    state: MfaState = "required" if factor else ("enrollment_required" if user.mfa_required else "verified")
    issued = _issue_session(db, user, mfa_verified=(state == "verified"), ip=ip, user_agent=user_agent)
    audit.record(db, user_actor(user, ip, user_agent), "login_succeeded", "user", user.id, {"mfa_state": state})
    return LoginOutcome(ok=True, issued=issued, user=user, mfa_state=state)


@dataclass(frozen=True)
class ExternalAccount:
    """What another module (single sign-on) may know about a staff account."""

    user_id: uuid.UUID
    email: str
    active: bool


def find_account_by_email(db: Session, email: str) -> ExternalAccount | None:
    try:
        normalized = normalize_email(email)
    except ValidationFailed:
        return None
    user = db.scalar(select(User).where(User.email == normalized))
    return ExternalAccount(user.id, user.email, user.status == "active") if user else None


def find_account(db: Session, user_id: uuid.UUID) -> ExternalAccount | None:
    user = db.get(User, user_id)
    return ExternalAccount(user.id, user.email, user.status == "active") if user else None


def start_external_session(
    db: Session,
    user_id: uuid.UUID,
    method: str,
    mfa_satisfied: bool,
    ip: str | None,
    user_agent: str | None,
) -> LoginOutcome:
    """Sign-in vouched for by an identity provider (single sign-on).

    The provider replaces the password check only. Two-step verification still applies unless
    ``mfa_satisfied`` (the provider reported a multi-factor sign-in and Mixt chose to accept it).
    Suspended or deactivated accounts cannot sign in this way either.
    """
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        return LoginOutcome(ok=False)
    now = now_utc()
    user.failed_login_count = 0
    user.last_login_at = now
    factor = _confirmed_factor(db, user.id)
    if mfa_satisfied:
        state: MfaState = "verified"
    else:
        state = "required" if factor else ("enrollment_required" if user.mfa_required else "verified")
    issued = _issue_session(db, user, mfa_verified=(state == "verified"), ip=ip, user_agent=user_agent)
    audit.record(
        db,
        user_actor(user, ip, user_agent),
        "login_succeeded",
        "user",
        user.id,
        {"mfa_state": state, "method": method, "mfa_by_provider": mfa_satisfied},
    )
    return LoginOutcome(ok=True, issued=issued, user=user, mfa_state=state)


def mfa_state_for(db: Session, user: User, row: UserSession) -> MfaState:
    if row.mfa_verified:
        return "verified"
    return (
        "required" if _confirmed_factor(db, user.id) else ("enrollment_required" if user.mfa_required else "verified")
    )


@dataclass(frozen=True)
class TotpSetup:
    secret: str
    provisioning_uri: str


def start_totp_enrollment(db: Session, actor: Actor, user: User) -> TotpSetup:
    if _confirmed_factor(db, user.id) is not None:
        raise Conflict("MFA_ALREADY_ENROLLED", "An authenticator is already set up for this user.")
    db.execute(delete(UserMfaFactor).where(UserMfaFactor.user_id == user.id, UserMfaFactor.confirmed_at.is_(None)))
    secret = mfa.new_secret()
    factor = UserMfaFactor(id=uuid7(), user_id=user.id, kind="totp", secret_ciphertext=b"", key_id="")
    encrypted = crypto.encrypt_text(secret, _factor_aad(factor.id))
    factor.secret_ciphertext, factor.key_id = encrypted.ciphertext, encrypted.key_id
    db.add(factor)
    db.flush()
    audit.record(db, actor, "mfa_enrollment_started", "user", user.id)
    return TotpSetup(secret=secret, provisioning_uri=mfa.provisioning_uri(secret, user.email))


def _check_code(db: Session, factor: UserMfaFactor, code: str) -> bool:
    secret = crypto.decrypt_text(crypto.EncryptedValue(factor.secret_ciphertext, factor.key_id), _factor_aad(factor.id))
    step = mfa.verify(secret, code, factor.last_used_step)
    if step is None:
        return False
    factor.last_used_step = step
    return True


def confirm_totp_enrollment(db: Session, actor: Actor, user: User, row: UserSession, code: str) -> IssuedSession | None:
    """Return a rotated, MFA-verified session, or None if the code is wrong (caller commits, replies 401)."""
    factor = db.scalar(
        select(UserMfaFactor).where(UserMfaFactor.user_id == user.id, UserMfaFactor.confirmed_at.is_(None))
    )
    if factor is None:
        raise Conflict("MFA_ENROLLMENT_NOT_STARTED", "Start authenticator set-up first.")
    if not _check_code(db, factor, code):
        _register_failure(db, user, actor.ip, actor.user_agent, "bad_mfa_code")
        return None
    factor.confirmed_at = now_utc()
    audit.record(db, actor, "mfa_enrolled", "user", user.id)
    return _rotate(db, row, user, mfa_verified=True)


def verify_mfa(db: Session, actor: Actor, user: User, row: UserSession, code: str) -> IssuedSession | None:
    factor = _confirmed_factor(db, user.id)
    if factor is None:
        raise Conflict("MFA_NOT_ENROLLED", "No authenticator is set up for this user.")
    if not _check_code(db, factor, code):
        _register_failure(db, user, actor.ip, actor.user_agent, "bad_mfa_code")
        return None
    user.failed_login_count = 0
    audit.record(db, actor, "mfa_verified", "user", user.id)
    return _rotate(db, row, user, mfa_verified=True)


def change_password(db: Session, actor: Actor, user: User, row: UserSession, current: str, new: str) -> None:
    if not passwords.verify_password(user.password_hash, current):
        raise PermissionDenied("INVALID_CURRENT_PASSWORD", "The current password is not correct.")
    if current == new:
        raise ValidationFailed("PASSWORD_UNCHANGED", "Choose a password different from the current one.")
    passwords.check_policy(new, user.email)
    user.password_hash = passwords.hash_password(new)
    user.must_change_password = False
    revoke_all_sessions(db, user.id, except_session_id=row.id)
    audit.record(db, actor, "password_changed", "user", user.id)


# --------------------------------------------------------------------------- user management


@dataclass(frozen=True)
class RoleGrant:
    role_key: str
    market_id: uuid.UUID | None = None


def _role_permissions(db: Session, role_ids: list[uuid.UUID]) -> set[str]:
    return set(db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id.in_(role_ids))))


def _check_can_grant(db: Session, access: Access, roles: list[Role], grants: list[RoleGrant]) -> None:
    """A user can only grant roles whose permissions they hold themselves, in the same scope."""
    by_key = {r.key: r for r in roles}
    for grant in grants:
        role = by_key[grant.role_key]
        for permission in _role_permissions(db, [role.id]):
            if not access.has(permission, grant.market_id):
                raise PermissionDenied(
                    "CANNOT_GRANT_ROLE",
                    f"You cannot grant role '{grant.role_key}' because you do not hold '{permission}' in that scope.",
                )


def _load_roles(db: Session, grants: list[RoleGrant]) -> list[Role]:
    keys = {g.role_key for g in grants}
    roles = list(db.scalars(select(Role).where(Role.key.in_(keys))))
    missing = keys - {r.key for r in roles}
    if missing:
        raise ValidationFailed("UNKNOWN_ROLE", f"Unknown role(s): {', '.join(sorted(missing))}.")
    return roles


def create_user(
    db: Session,
    actor: Actor,
    access: Access,
    email: str,
    full_name: str,
    temporary_password: str,
    grants: list[RoleGrant],
    timezone: str = "UTC",
) -> User:
    access.require("users.manage")
    normalized = normalize_email(email)
    if db.scalar(select(User.id).where(User.email == normalized)) is not None:
        raise Conflict("EMAIL_IN_USE", "A user with this email already exists.")
    try:
        validate_timezone(timezone)
    except InvalidTimezone as exc:
        raise ValidationFailed("INVALID_TIMEZONE", str(exc)) from exc
    passwords.check_policy(temporary_password, normalized)
    roles = _load_roles(db, grants)
    _check_can_grant(db, access, roles, grants)

    principal = Principal(kind="user", display_name=full_name.strip())
    db.add(principal)
    db.flush()
    user = User(
        principal_id=principal.id,
        email=normalized,
        full_name=full_name.strip(),
        password_hash=passwords.hash_password(temporary_password),
        must_change_password=True,
        timezone=timezone,
    )
    db.add(user)
    by_key = {r.key: r for r in roles}
    for grant in grants:
        db.add(
            PrincipalRole(
                principal_id=principal.id,
                role_id=by_key[grant.role_key].id,
                market_id=grant.market_id,
                granted_by=actor.principal_id,
            )
        )
    db.flush()
    audit.record(
        db,
        actor,
        "user_created",
        "user",
        user.id,
        {"email": normalized, "roles": [{"role": g.role_key, "market_id": g.market_id} for g in grants]},
    )
    return user


def set_user_status(db: Session, actor: Actor, access: Access, user_id: uuid.UUID, status: str) -> User:
    access.require("users.manage")
    if status not in ("active", "suspended", "deactivated"):
        raise ValidationFailed("INVALID_STATUS", "Status must be active, suspended or deactivated.")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "User not found.")
    if user.id == actor.user_id and status != "active":
        raise Conflict("CANNOT_DEACTIVATE_SELF", "You cannot suspend or deactivate your own account.")
    before = user.status
    user.status = status
    if status != "active":
        revoke_all_sessions(db, user.id)
    audit.record(db, actor, "user_status_changed", "user", user.id, {"status": {"from": before, "to": status}})
    return user


def grant_roles(db: Session, actor: Actor, access: Access, user_id: uuid.UUID, grants: list[RoleGrant]) -> None:
    access.require("users.manage")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "User not found.")
    roles = _load_roles(db, grants)
    _check_can_grant(db, access, roles, grants)
    by_key = {r.key: r for r in roles}
    for grant in grants:
        exists = db.scalar(
            select(PrincipalRole.id).where(
                PrincipalRole.principal_id == user.principal_id,
                PrincipalRole.role_id == by_key[grant.role_key].id,
                PrincipalRole.market_id.is_(None)
                if grant.market_id is None
                else PrincipalRole.market_id == grant.market_id,
            )
        )
        if exists is None:
            db.add(
                PrincipalRole(
                    principal_id=user.principal_id,
                    role_id=by_key[grant.role_key].id,
                    market_id=grant.market_id,
                    granted_by=actor.principal_id,
                )
            )
    db.flush()
    audit.record(
        db,
        actor,
        "roles_granted",
        "user",
        user.id,
        {"roles": [{"role": g.role_key, "market_id": g.market_id} for g in grants]},
    )


def revoke_role(db: Session, actor: Actor, access: Access, user_id: uuid.UUID, grant: RoleGrant) -> None:
    access.require("users.manage")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "User not found.")
    if user.id == actor.user_id and grant.role_key == "owner":
        raise Conflict("CANNOT_REVOKE_OWN_OWNER_ROLE", "You cannot remove your own Owner role.")
    roles = _load_roles(db, [grant])
    _check_can_grant(db, access, roles, [grant])
    result = db.execute(
        delete(PrincipalRole).where(
            PrincipalRole.principal_id == user.principal_id,
            PrincipalRole.role_id == roles[0].id,
            PrincipalRole.market_id.is_(None)
            if grant.market_id is None
            else PrincipalRole.market_id == grant.market_id,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound("ROLE_NOT_ASSIGNED", "This role is not assigned in that scope.")
    audit.record(db, actor, "role_revoked", "user", user.id, {"role": grant.role_key, "market_id": grant.market_id})


def list_roles(db: Session, access: Access) -> list[tuple[Role, list[str]]]:
    access.require("users.read")
    roles = list(db.scalars(select(Role).order_by(Role.key)))
    return [
        (r, sorted(db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == r.id))))
        for r in roles
    ]


def get_user(db: Session, access: Access, user_id: uuid.UUID) -> User:
    access.require("users.read")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "User not found.")
    return user


def user_is_active(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(select(User.id).where(User.id == user_id, User.status == "active")) is not None


def list_users(db: Session, access: Access) -> list[User]:
    access.require("users.read")
    return list(db.scalars(select(User).order_by(User.full_name)))


def roles_of(db: Session, principal_id: uuid.UUID) -> list[tuple[str, uuid.UUID | None]]:
    rows = db.execute(
        select(Role.key, PrincipalRole.market_id)
        .join(PrincipalRole, PrincipalRole.role_id == Role.id)
        .where(PrincipalRole.principal_id == principal_id)
        .order_by(Role.key)
    ).all()
    return [(r[0], r[1]) for r in rows]


def bootstrap_owner(db: Session, actor: Actor, email: str, full_name: str, password: str) -> User:
    """Create the first Owner. Refuses if any user already exists (use the API afterwards)."""
    if db.scalar(select(User.id).limit(1)) is not None:
        raise Conflict("ALREADY_BOOTSTRAPPED", "Users already exist; create further users through the API.")
    normalized = normalize_email(email)
    passwords.check_policy(password, normalized)
    principal = Principal(kind="user", display_name=full_name)
    db.add(principal)
    db.flush()
    user = User(
        principal_id=principal.id,
        email=normalized,
        full_name=full_name,
        password_hash=passwords.hash_password(password),
        must_change_password=False,
    )
    db.add(user)
    owner = db.scalar(select(Role).where(Role.key == "owner"))
    if owner is None:
        raise NotFound("ROLE_NOT_FOUND", "Owner role missing; run migrations first.")
    db.add(PrincipalRole(principal_id=principal.id, role_id=owner.id, market_id=None, granted_by=actor.principal_id))
    db.flush()
    audit.record(db, actor, "owner_bootstrapped", "user", user.id, {"email": normalized})
    return user
