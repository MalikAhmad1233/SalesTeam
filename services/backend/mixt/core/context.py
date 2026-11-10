"""Who is acting, passed explicitly into every service call that changes data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

PrincipalKind = Literal["user", "agent", "system", "integration"]

# Seeded by the first migration; used for migrations, seeds and scheduled system jobs.
SYSTEM_PRINCIPAL_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")


@dataclass(frozen=True, slots=True)
class Actor:
    principal_id: uuid.UUID
    kind: PrincipalKind
    user_id: uuid.UUID | None = None
    ip: str | None = None
    user_agent: str | None = None
    correlation_id: str | None = None


SYSTEM_ACTOR = Actor(principal_id=SYSTEM_PRINCIPAL_ID, kind="system")
