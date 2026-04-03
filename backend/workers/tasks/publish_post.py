import httpx
import structlog

from backend.workers.broker import broker

logger = structlog.get_logger()

# Тестовий URL n8n. Воркер запускається локально, тому 127.0.0.1:5678
N8N_WEBHOOK_URL = "http://127.0.0.1:5678/webhook-test/publish-post"


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
            response = await client.post(N8N_WEBHOOK_URL, json=payload, timeout=10.0)
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
