import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse

from backend.services.exceptions import (
    DraftNotFoundError,
    PublishingFailedError,
    UnsupportedPlatformError,
)

logger = structlog.get_logger()

_PROBLEM_TYPE_BASE = "https://serotonin-script.internal/errors"


def _problem(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    extra: dict[str, object] | None = None,
) -> JSONResponse:
    """Return an RFC 7807 Problem Details response."""
    body: dict[str, object] = {
        "type": f"{_PROBLEM_TYPE_BASE}/{title.lower().replace(' ', '-')}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


async def domain_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map domain errors to structured RFC 7807 HTTP responses."""
    if isinstance(exc, DraftNotFoundError):
        return _problem(
            request,
            status.HTTP_404_NOT_FOUND,
            "Draft Not Found",
            str(exc),
            {"draft_id": str(exc.draft_id)},
        )
    if isinstance(exc, UnsupportedPlatformError):
        return _problem(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unsupported Platform",
            str(exc),
            {"platform": exc.platform},
        )
    if isinstance(exc, PublishingFailedError):
        logger.error(
            "publishing_failed",
            platform=str(exc.platform),
            reason=exc.reason,
            path=request.url.path,
        )
        return _problem(
            request,
            status.HTTP_502_BAD_GATEWAY,
            "Publishing Failed",
            str(exc),
            {"platform": str(exc.platform)},
        )
    # Catch-all for any future DomainError subclasses
    logger.error("unhandled_domain_error", error=str(exc), path=request.url.path)
    return _problem(
        request,
        status.HTTP_400_BAD_REQUEST,
        "Domain Error",
        str(exc),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all unhandled exceptions and return a 500 RFC 7807 response."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
    )
    return _problem(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Internal Server Error",
        "An unexpected error occurred.",
    )
