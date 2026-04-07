import structlog
from taskiq import TaskiqMessage, TaskiqMiddleware

logger = structlog.get_logger()


class RetryTrackerMiddleware(TaskiqMiddleware):
    """Taskiq middleware that logs warning messages for retry attempts."""

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Log a warning if this task execution is a retry attempt."""
        # Taskiq stores the retry count in message labels
        retry_count = message.labels.get("retry_count", 0)

        if int(retry_count) > 0:
            logger.warning(
                "task_retry_attempt",
                task_id=message.task_id,
                task_name=message.task_name,
                attempt=retry_count,
            )
        return message
