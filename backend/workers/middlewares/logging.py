from typing import Any

import structlog
from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

logger = structlog.get_logger()


class StructlogMiddleware(TaskiqMiddleware):
    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Виконується безпосередньо перед запуском таску у воркері."""
        logger.info(
            "task_execution_started",
            task_id=message.task_id,
            task_name=message.task_name,
        )
        return message

    def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Виконується після завершення таску (успішного або з помилкою)."""
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
