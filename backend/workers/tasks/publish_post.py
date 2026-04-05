import httpx
import structlog

from backend.config.settings import settings
from backend.workers.broker import broker

logger = structlog.get_logger()


@broker.task(task_name="publish_post", timeout=30, labels={"priority": "medium"})
async def publish_post_task(
    post_id: str,
    platform: str,
    content: str,
) -> dict[str, str]:
    """Фонова задача для відправки контенту в n8n оркестратор."""
    logger.info("publish_task_started", post_id=post_id, platform=platform)

    payload = {"post_id": post_id, "platform": platform, "content": content}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(settings.N8N_WEBHOOK_URL, json=payload, timeout=10.0)
            response.raise_for_status()

        logger.info("publish_task_success", post_id=post_id, platform=platform)
        return {"status": "success", "post_id": post_id, "platform": platform}

    except Exception as e:
        logger.error(
            "publish_task_failed",
            post_id=post_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
