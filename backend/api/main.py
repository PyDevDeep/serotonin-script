import structlog
from fastapi import FastAPI

from backend.api.middleware.error_handler import (
    domain_exception_handler,
    global_exception_handler,
)
from backend.api.middleware.logging import StructuredLoggingMiddleware
from backend.api.routes import drafts, feedback, health
from backend.config.settings import settings
from backend.services.exceptions import DomainError

# Basic structlog configuration for JSON output
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(StructuredLoggingMiddleware)
    app.add_exception_handler(DomainError, domain_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(drafts.router, prefix="/api/v1")
    app.include_router(feedback.router, prefix="/api/v1")

    return app


app = create_app()
