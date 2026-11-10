"""FastAPI application factory."""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import mixt.models  # noqa: F401  (registers every table so foreign keys resolve)
from mixt.api.routers import audit, auth, crm, health, reference, settings, users
from mixt.core.config import get_config
from mixt.core.errors import DomainError
from mixt.core.logging import configure_logging, get_logger

PROBLEM_JSON = "application/problem+json"
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
log = get_logger("mixt.api")


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
    app = FastAPI(
        title="Mixt AI API",
        version="0.1.0",
        description="Mixt AI backend. Phase 1a: identity, reference data, settings, audit and core CRM.",
        openapi_url="/api/v1/openapi.json",
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
        return _problem(exc.status, exc.title, exc.code, exc.detail, request, **exc.extra)

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
    app.include_router(users.router, prefix=prefix)
    app.include_router(reference.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(crm.router, prefix=prefix)
    return app
