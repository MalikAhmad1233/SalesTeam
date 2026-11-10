"""Domain errors, rendered by the API as RFC 9457 ``application/problem+json``.

Every error has a stable machine-readable ``code`` that clients and agents can rely on.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status: int = 400
    title: str = "Request could not be completed"

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra


class ValidationFailed(DomainError):
    status = 422
    title = "Validation failed"


class NotFound(DomainError):
    status = 404
    title = "Not found"


class AuthenticationRequired(DomainError):
    status = 401
    title = "Authentication required"


class PermissionDenied(DomainError):
    status = 403
    title = "Permission denied"


class Conflict(DomainError):
    status = 409
    title = "Conflict"


class PreconditionFailed(DomainError):
    status = 412
    title = "Precondition failed"


class PreconditionRequired(DomainError):
    status = 428
    title = "Precondition required"


class Locked(DomainError):
    status = 423
    title = "Locked"
