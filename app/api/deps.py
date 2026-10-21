"""Shared request helpers: service lookup and the (development-only) staff key check."""

import hmac

from fastapi import Header, Request

from app.core.errors import NotConfiguredError, UnauthorizedError
from app.services.cases import CaseService


def get_service(request: Request) -> CaseService:
    return request.app.state.case_service


def get_correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def require_staff(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Placeholder protection for staff endpoints. This is NOT real authentication.

    A single shared key in a header is only acceptable for local development. For anything
    public you need per-user login, roles and rate limiting (see docs/security.md).
    """
    expected: str = request.app.state.settings.staff_api_key
    if not expected:
        raise NotConfiguredError(
            "STAFF_API_KEY is not set, so staff endpoints are disabled. Set it in .env."
        )
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise UnauthorizedError("Missing or invalid X-API-Key header.")
