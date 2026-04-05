from unittest.mock import AsyncMock

import pytest

from backend.services.content_generator import JudgeFailedError
from backend.workers.tasks.generate_draft import generate_draft_task


@pytest.mark.asyncio
async def test_generate_draft_task_success():
    """
    Тестує успішне виконання фонової задачі генерації.
    Перевіряє, чи правильно викликається внутрішній сервіс (ContentGenerator).
    """
    # Arrange: Створюємо мок для ContentGenerator
    mock_generator = AsyncMock()
    mock_generator.generate_draft.return_value = "Згенерований медичний текст"

    topic = "Симптоми тривоги"
    platform = "telegram"
    source_url = "https://pubmed.org/123"

    # Act: Прямий виклик функції (в обхід брокера) з ін'єкцією мока
    result: str = await generate_draft_task(
        topic=topic,
        platform=platform,
        source_url=source_url,
        generator=mock_generator,
        session=AsyncMock(),
    )

    # Assert: Перевіряємо результат та аргументи виклику
    assert result == "Згенерований медичний текст"
    mock_generator.generate_draft.assert_called_once_with(
        topic=topic, platform=platform, source_url=source_url
    )


@pytest.mark.asyncio
async def test_generate_draft_task_judge_failure():
    """
    Тестує поведінку воркера, коли LLM-суддя відхиляє драфт після всіх спроб.
    Воркер повинен прокинути помилку далі, щоб Taskiq зафіксував FAILED статус.
    """
    # Arrange
    mock_generator = AsyncMock()
    mock_generator.generate_draft.side_effect = JudgeFailedError(
        topic="Стрес", attempts=3, draft="Брудний текст"
    )

    # Act & Assert
    with pytest.raises(JudgeFailedError) as exc_info:
        await generate_draft_task(
            topic="Стрес",
            platform="twitter",
            source_url=None,
            generator=mock_generator,
            session=AsyncMock(),
        )

    assert exc_info.value.topic == "Стрес"
    assert exc_info.value.attempts == 3
    assert exc_info.value.draft == "Брудний текст"


@pytest.mark.asyncio
async def test_generate_draft_task_unexpected_error():
    """
    Тестує поведінку при непередбачуваній помилці (наприклад, відвал БД або API OpenAI).
    """
    # Arrange
    mock_generator = AsyncMock()
    mock_generator.generate_draft.side_effect = Exception(
        "OpenAI API 500 Internal Server Error"
    )

    # Act & Assert
    with pytest.raises(Exception, match="OpenAI API 500"):
        await generate_draft_task(
            topic="Мігрень",
            platform="threads",
            source_url=None,
            generator=mock_generator,
            session=AsyncMock(),
        )
