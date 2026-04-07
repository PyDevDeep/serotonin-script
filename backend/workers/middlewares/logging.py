from typing import Any

import structlog
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

logger = structlog.get_logger()


class StructlogMiddleware(TaskiqMiddleware):
    """Taskiq middleware that logs task start and completion via structlog."""

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Log task start details before the task executes in the worker."""
        logger.info(
            "task_execution_started",
            task_id=message.task_id,
            task_name=message.task_name,
        )
        return message

    def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Log task completion or failure after execution."""
        if result.is_err:
            logger.error(
                "task_execution_failed",
                task_id=message.task_id,
                task_name=message.task_name,
                error=str(result.error),
            )
        else:
            logger.info(
                "task_execution_success",
                task_id=message.task_id,
                task_name=message.task_name,
                execution_time_sec=round(result.execution_time, 3),
            )
