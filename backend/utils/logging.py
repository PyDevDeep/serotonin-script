import logging
import sys

import structlog

_EXCLUDED_ACCESS_PATHS = {"/api/v1/health", "/api/v1/ready", "/metrics"}


class _UvicornAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in _EXCLUDED_ACCESS_PATHS)


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

    # Suppress noisy access log lines for health/metrics endpoints
    logging.getLogger("uvicorn.access").addFilter(_UvicornAccessFilter())
