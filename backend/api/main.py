from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from backend.api.middleware.error_handler import (
    domain_exception_handler,
    global_exception_handler,
)
from backend.api.middleware.logging import StructuredLoggingMiddleware
from backend.api.routes import drafts, feedback, health
from backend.config.settings import settings
from backend.services.exceptions import DomainError
from backend.utils.logging import setup_logging

setup_logging()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    app.add_middleware(StructuredLoggingMiddleware)
    app.add_exception_handler(DomainError, domain_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(drafts.router, prefix="/api/v1")
    app.include_router(feedback.router, prefix="/api/v1")

    return app


app = create_app()
