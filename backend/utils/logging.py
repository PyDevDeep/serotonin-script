import logging
import sys

import structlog


def setup_logging() -> None:
    """Configure structlog for JSON output compatible with Loki/Grafana.

    Sets up structured JSON logging for both the application and standard
    library loggers (e.g. uvicorn). Must be called once at process startup,
    before creating any loggers.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.ExceptionRenderer(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Route standard library loggers (uvicorn, sqlalchemy, etc.) through structlog
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
