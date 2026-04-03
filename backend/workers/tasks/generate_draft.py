from typing import Annotated

import structlog
from taskiq import TaskiqDepends

from backend.services.content_generator import ContentGenerator, JudgeFailedError
from backend.workers.broker import broker
from backend.workers.dependencies import get_content_generator

logger = structlog.get_logger()


# Збільшено timeout до 180 секунд через наявність циклу LLM-as-a-Judge та Retries
@broker.task(task_name="generate_medical_draft", timeout=180)
async def generate_draft_task(
    topic: str,
    platform: str,
    generator: Annotated[ContentGenerator, TaskiqDepends(get_content_generator)],
    source_url: str | None = None,
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
    )

    try:
        result = await generator.generate_draft(
            topic=topic, platform=platform, source_url=source_url
        )
        logger.info(
            "background_task_success", task="generate_medical_draft", topic=topic
        )
        return result

    except JudgeFailedError as e:
        # Специфічна обробка помилки валідації LLM
        logger.error(
            "background_task_judge_failed",
            task="generate_medical_draft",
            topic=e.topic,
            attempts=e.attempts,
        )
        # Навіть якщо суддя відхилив, ми можемо кинути помилку або зберегти "чорновий" драфт.
        # Зараз кидаємо виняток, щоб Taskiq зафіксував статус Failure.
        raise

    except Exception as e:
        logger.error(
            "background_task_failed",
            task="generate_medical_draft",
            topic=topic,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
