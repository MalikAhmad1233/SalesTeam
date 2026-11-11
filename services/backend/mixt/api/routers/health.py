"""Liveness (the process answers) and readiness (it can do useful work: database reachable, schema
at the revision this build needs, rate-limit store reachable when configured)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from mixt.core import schema
from mixt.core.config import get_config
from mixt.core.db import get_session
from mixt.core.ratelimit import RedisRateLimiter, limiter_for

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=None)
def readiness(db: Session = Depends(get_session, scope="function")) -> dict[str, str] | JSONResponse:
    db.execute(text("SELECT 1"))
    checks = {"database": "ok"}
    head = schema.expected_head()
    revision = schema.current_revision(db.connection())
    checks["schema"] = "ok" if head is None or revision == head else "behind"
    limiter = limiter_for(get_config())
    if isinstance(limiter, RedisRateLimiter):
        checks["rate_limit_store"] = "ok" if limiter.ping() else "unreachable"
    if any(v != "ok" for v in checks.values()):
        return JSONResponse({"status": "not_ready", **checks}, status_code=503)
    return {"status": "ready", **checks}
