import time
import uuid
from typing import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs each request with a unique request ID and timing."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process the request, inject a request ID, and log duration and status."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Bind request_id to the logger context for this specific request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time

            logger.info(
                "request_completed",
                status_code=response.status_code,
                process_time_ms=round(process_time * 1000, 2),
            )

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            process_time = time.perf_counter() - start_time
            logger.error(
                "request_failed",
                error=str(e),
                process_time_ms=round(process_time * 1000, 2),
            )
            raise
