from typing import Any

from prometheus_client import Counter, Histogram
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

TASKS_TOTAL = Counter(
    "taskiq_tasks_total",
    "Total tasks executed",
    ["task_name", "status"],
)

TASK_DURATION = Histogram(
    "taskiq_task_duration_seconds",
    "Task execution time in seconds",
    ["task_name"],
)


class PrometheusMetricsMiddleware(TaskiqMiddleware):
    """Taskiq middleware that records task execution counts and durations."""

    def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Increment counters and observe duration after each task execution."""
        status = "error" if result.is_err else "success"
        TASKS_TOTAL.labels(task_name=message.task_name, status=status).inc()
        TASK_DURATION.labels(task_name=message.task_name).observe(result.execution_time)
