"""Resolved permissions for one principal, including market scopes and teams they lead.

A role assigned with ``market_id = NULL`` grants its permissions in every market; a role assigned
with a market grants them only for records in that market.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from mixt.core.context import SYSTEM_PRINCIPAL_ID, Actor
from mixt.core.errors import PermissionDenied
from mixt.modules.identity.models import PrincipalRole, Role, RolePermission, TeamMember

ALL_MARKETS: None = None


@dataclass(frozen=True)
class Access:
    principal_id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None
    grants: Mapping[str, frozenset[uuid.UUID | None]]
    led_team_user_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    role_keys: frozenset[str] = field(default_factory=frozenset)

    def has(self, permission: str, market_id: uuid.UUID | None = None) -> bool:
        scopes = self.grants.get(permission)
        if not scopes:
            return False
        return ALL_MARKETS in scopes or (market_id is not None and market_id in scopes)

    def has_globally(self, permission: str) -> bool:
        return ALL_MARKETS in self.grants.get(permission, frozenset())

    def has_somewhere(self, permission: str) -> bool:
        return bool(self.grants.get(permission))

    def market_scopes(self, permission: str) -> frozenset[uuid.UUID]:
        return frozenset(m for m in self.grants.get(permission, frozenset()) if m is not None)

    def require(self, permission: str, market_id: uuid.UUID | None = None) -> None:
        if not self.has(permission, market_id):
            raise PermissionDenied("PERMISSION_DENIED", f"Missing permission '{permission}'.", permission=permission)

    def require_somewhere(self, permission: str) -> None:
        if not self.has_somewhere(permission):
            raise PermissionDenied("PERMISSION_DENIED", f"Missing permission '{permission}'.", permission=permission)


def load_access(session: Session, actor: Actor) -> Access:
    rows = session.execute(
        select(RolePermission.permission_key, PrincipalRole.market_id, Role.key)
        .join(Role, Role.id == RolePermission.role_id)
        .join(PrincipalRole, PrincipalRole.role_id == Role.id)
        .where(PrincipalRole.principal_id == actor.principal_id)
    ).all()
    grants: dict[str, set[uuid.UUID | None]] = {}
    role_keys: set[str] = set()
    for permission_key, market_id, role_key in rows:
        grants.setdefault(permission_key, set()).add(market_id)
        role_keys.add(role_key)

    led: frozenset[uuid.UUID] = frozenset()
    if actor.user_id is not None:
        led_teams = select(TeamMember.team_id).where(
            TeamMember.user_id == actor.user_id, TeamMember.team_role == "lead"
        )
        led = frozenset(session.scalars(select(TeamMember.user_id).where(TeamMember.team_id.in_(led_teams))))

    return Access(
        principal_id=actor.principal_id,
        kind=actor.kind,
        user_id=actor.user_id,
        grants={k: frozenset(v) for k, v in grants.items()},
        led_team_user_ids=led,
        role_keys=frozenset(role_keys),
    )


def system_access(*permissions: str) -> Access:
    """Access for work the system does on its own (a webhook, a public form), limited to ``permissions``.

    It has no user, so anything it creates is unowned and goes to the pool for a person to pick up.
    """
    return Access(
        principal_id=SYSTEM_PRINCIPAL_ID,
        kind="system",
        user_id=None,
        grants={p: frozenset({ALL_MARKETS}) for p in permissions},
    )
