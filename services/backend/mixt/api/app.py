"""FastAPI application factory."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import mixt.wiring  # noqa: F401  (tables, event consumers, validators)
from mixt.api import startup, throttle
from mixt.api.net import resolve_client_ip
from mixt.api.routers import audit, auth, crm, engagement, health, leads, pipeline, reference, settings, sso, users
from mixt.core.config import get_config
from mixt.core.db import get_engine
from mixt.core.errors import DomainError
from mixt.core.logging import configure_logging, get_logger

PROBLEM_JSON = "application/problem+json"
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
log = get_logger("mixt.api")


_UNMETERED_PATHS = ("/api/v1/health",)


def _problem(status: int, title: str, code: str, detail: str, request: Request, **extra: object) -> JSONResponse:
    body = {
        "type": f"https://errors.mixt.ai/{code.lower().replace('_', '-')}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": request.url.path,
        "correlation_id": getattr(request.state, "correlation_id", None),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def create_app() -> FastAPI:
    config = get_config()
    configure_logging(config.log_level, config.log_json)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(startup.run, config, get_engine())
        yield

    app = FastAPI(
        lifespan=lifespan,
        title="Mixt AI API",
        version="0.1.0",
        description="Mixt AI backend: identity, reference data, settings, audit, CRM, leads, pipeline and tasks.",
        # The schema and interactive docs are for development; deployed environments do not publish them.
        openapi_url="/api/v1/openapi.json" if config.env.value in ("local", "test") else None,
        docs_url="/api/docs" if config.env.value in ("local", "test") else None,
        redoc_url=None,
    )

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", "If-Match", "X-Correlation-Id", "Idempotency-Key"],
        )

    @app.middleware("http")
    async def correlation_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-correlation-id", "")
        correlation_id = incoming if _CORRELATION_RE.match(incoming) else uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        try:
            path = request.url.path
            if path.startswith("/api/") and not path.startswith(_UNMETERED_PATHS):
                ip = resolve_client_ip(request, config.trusted_proxies)
                decision = await run_in_threadpool(throttle.check, "api_per_ip", ip)
                if not decision.allowed:
                    log.warning("rate_limited", limit="api_per_ip", retry_after=decision.retry_after_seconds)
                    response: Response = _problem(
                        429,
                        "Too many requests",
                        "RATE_LIMITED",
                        throttle.MESSAGES["api_per_ip"],
                        request,
                        retry_after_seconds=decision.retry_after_seconds,
                        limit="api_per_ip",
                    )
                    response.headers["Retry-After"] = str(decision.retry_after_seconds)
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if config.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        if exc.status >= 500:
            log.error("domain_error", code=exc.code)
        response = _problem(exc.status, exc.title, exc.code, exc.detail, request, **exc.extra)
        response.headers.update(getattr(exc, "headers", {}))
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _problem(
            422,
            "Validation failed",
            "REQUEST_VALIDATION_FAILED",
            "The request body or parameters are invalid.",
            request,
            errors=errors,
        )

    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(sso.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(reference.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(crm.router, prefix=prefix)
    app.include_router(leads.router, prefix=prefix)
    app.include_router(pipeline.router, prefix=prefix)
    app.include_router(engagement.router, prefix=prefix)
    return app
