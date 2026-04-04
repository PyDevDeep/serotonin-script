from typing import Annotated

import structlog
from taskiq import TaskiqDepends

from backend.services.content_generator import ContentGenerator, JudgeFailedError
from backend.workers.broker import broker
from backend.workers.callbacks import notify_slack_on_complete, notify_slack_on_failure
from backend.workers.dependencies import get_content_generator

logger = structlog.get_logger()


# Збільшено timeout до 180 секунд через наявність циклу LLM-as-a-Judge та Retries
@broker.task(task_name="generate_medical_draft", timeout=180)
async def generate_draft_task(
    topic: str,
    platform: str,
    generator: Annotated[ContentGenerator, TaskiqDepends(get_content_generator)],
    source_url: str | None = None,
    user_id: str | None = None,
    channel_id: str | None = None,
    draft_id: str = "temp_id",
) -> str:
    """
    Фонова задача для генерації медичного контенту.
    """
    logger.info(
        "background_task_started",
        task="generate_medical_draft",
        topic=topic,
        platform=platform,
        source_url=source_url,
        user_id=user_id,
        channel_id=channel_id,
    )

    try:
        result = await generator.generate_draft(
            topic=topic, platform=platform, source_url=source_url
        )
        logger.info(
            "background_task_success", task="generate_medical_draft", topic=topic
        )

        # ДОДАНО: Відправка готового результату у Slack
        if user_id and channel_id:
            await notify_slack_on_complete(
                user_id=user_id,
                channel_id=channel_id,
                draft=result,
                topic=topic,
                draft_id=draft_id,
                platform=platform,
            )

        return result

    except JudgeFailedError as e:
        logger.error(
            "background_task_judge_failed",
            task="generate_medical_draft",
            topic=e.topic,
            attempts=e.attempts,
        )
        # ДОДАНО: Відправка повідомлення про провал валідації у Slack
        if user_id and channel_id:
            await notify_slack_on_failure(
                user_id=user_id,
                channel_id=channel_id,
                error_msg=f"Модель не пройшла валідацію після {e.attempts} спроб.\n\nОстанній драфт:\n{e.draft}",
                topic=topic,
            )
        raise

    except Exception as e:
        logger.error(
            "background_task_failed",
            task="generate_medical_draft",
            topic=topic,
            error=str(e),
            error_type=type(e).__name__,
        )
        # ДОДАНО: Відправка критичної помилки у Slack
        if user_id and channel_id:
            await notify_slack_on_failure(
                user_id=user_id, channel_id=channel_id, error_msg=str(e), topic=topic
            )
        raise
