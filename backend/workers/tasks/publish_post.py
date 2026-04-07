from typing import Annotated

import structlog
from taskiq import TaskiqDepends

from backend.services.publisher_service import PublisherService
from backend.workers.broker import broker
from backend.workers.dependencies import get_publisher_service

logger = structlog.get_logger()


@broker.task(task_name="publish_post", timeout=30, labels={"priority": "medium"})
async def publish_post_task(
    post_id: str,
    platform: str,
    content: str,
    publisher_service: Annotated[
        PublisherService, TaskiqDepends(get_publisher_service)
    ],
) -> dict[str, str]:
    """Trigger publishing via PublisherService. All routing logic lives in the service."""
    logger.info("publish_task_started", post_id=post_id, platform=platform)
    await publisher_service.publish(post_id=post_id, platform=platform, content=content)
    logger.info("publish_task_success", post_id=post_id, platform=platform)
    return {"status": "success", "post_id": post_id, "platform": platform}
