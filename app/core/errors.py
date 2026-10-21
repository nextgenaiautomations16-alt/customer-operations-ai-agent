"""Application errors. The API layer turns each of these into a consistent JSON response."""

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class InvalidTransitionError(AppError):
    status_code = 409
    code = "invalid_transition"


class IdempotencyConflictError(AppError):
    status_code = 409
    code = "idempotency_conflict"


class NoteRequiredError(AppError):
    status_code = 422
    code = "note_required"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class NotConfiguredError(AppError):
    status_code = 503
    code = "not_configured"
