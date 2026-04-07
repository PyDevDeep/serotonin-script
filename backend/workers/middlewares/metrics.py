from typing import Any

import structlog
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

logger = structlog.get_logger()


class PrometheusMetricsMiddleware(TaskiqMiddleware):
    """Taskiq middleware placeholder for Prometheus metrics collection."""

    def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Log a debug metrics event after task execution (placeholder for Prometheus integration)."""
        status = "error" if result.is_err else "success"
        logger.debug(
            "metrics_updated",
            metric="task_execution",
            task_name=message.task_name,
            status=status,
        )
