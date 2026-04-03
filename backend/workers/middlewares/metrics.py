from typing import Any

import structlog
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

logger = structlog.get_logger()


class PrometheusMetricsMiddleware(TaskiqMiddleware):
    def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """
        TODO: Інтеграція з prometheus_client.
        Тут будуть оновлюватись Counter (кількість задач) та Histogram (час виконання).
        """
        status = "error" if result.is_err else "success"
        logger.debug(
            "metrics_updated",
            metric="task_execution",
            task_name=message.task_name,
            status=status,
        )
