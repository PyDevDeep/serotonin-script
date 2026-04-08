from unittest.mock import AsyncMock, patch

import pytest

from backend.services.content_generator import JudgeFailedError
from backend.workers.tasks.generate_draft import generate_draft_task

# Path to patch Slack callbacks so tests don't make HTTP calls
_NOTIFY_COMPLETE = "backend.workers.tasks.generate_draft.notify_slack_on_complete"
_NOTIFY_FAILURE = "backend.workers.tasks.generate_draft.notify_slack_on_failure"


@pytest.mark.asyncio
async def test_generate_draft_task_success():
    """
    Тестує успішне виконання фонової задачі генерації.
    Перевіряє, чи правильно викликається внутрішній сервіс (ContentGenerator).
    """
    # Arrange: create a mock for ContentGenerator
    mock_generator = AsyncMock()
    mock_generator.generate_draft.return_value = "Згенерований медичний текст"

    topic = "Симптоми тривоги"
    platform = "telegram"
    source_url = "https://pubmed.org/123"

    # Act: call the function directly (bypassing the broker) with the injected mock
    result: str = await generate_draft_task(
        topic=topic,
        platform=platform,
        source_url=source_url,
        generator=mock_generator,
        session=AsyncMock(),
    )

    # Assert: verify the result and call arguments
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


@pytest.mark.asyncio
async def test_generate_draft_task_success_with_numeric_draft_id_saves_to_db():
    """draft_id.isdigit() → repo.update called with generated content."""
    mock_generator = AsyncMock()
    mock_generator.generate_draft.return_value = "Готовий пост"
    mock_session = AsyncMock()

    with patch("backend.workers.tasks.generate_draft.DraftRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        result = await generate_draft_task(
            topic="Тривога",
            platform="telegram",
            generator=mock_generator,
            session=mock_session,
            draft_id="42",
        )

    assert result == "Готовий пост"
    mock_repo.update.assert_awaited_once()
    call_args = mock_repo.update.call_args
    assert call_args.args[0] == 42


@pytest.mark.asyncio
async def test_generate_draft_task_success_with_slack_notification():
    """user_id + channel_id present → notify_slack_on_complete called."""
    mock_generator = AsyncMock()
    mock_generator.generate_draft.return_value = "Пост"

    with patch(_NOTIFY_COMPLETE) as mock_notify:
        mock_notify.return_value = None
        await generate_draft_task(
            topic="Депресія",
            platform="twitter",
            generator=mock_generator,
            session=AsyncMock(),
            user_id="U123",
            channel_id="C456",
        )

    mock_notify.assert_awaited_once()
    kwargs = mock_notify.call_args.kwargs
    assert kwargs["user_id"] == "U123"
    assert kwargs["channel_id"] == "C456"
    assert kwargs["topic"] == "Депресія"


@pytest.mark.asyncio
async def test_generate_draft_task_judge_failure_with_slack_notification():
    """JudgeFailedError + user_id/channel_id → notify_slack_on_complete(is_valid=False)."""
    mock_generator = AsyncMock()
    mock_generator.generate_draft.side_effect = JudgeFailedError(
        topic="Стрес", attempts=2, draft="Поганий текст"
    )

    with patch(_NOTIFY_COMPLETE) as mock_notify:
        mock_notify.return_value = None
        with pytest.raises(JudgeFailedError):
            await generate_draft_task(
                topic="Стрес",
                platform="telegram",
                generator=mock_generator,
                session=AsyncMock(),
                user_id="U999",
                channel_id="C999",
            )

    mock_notify.assert_awaited_once()
    assert mock_notify.call_args.kwargs["is_valid"] is False


@pytest.mark.asyncio
async def test_generate_draft_task_unexpected_error_with_slack_notification():
    """Generic exception + user_id/channel_id → notify_slack_on_failure called."""
    mock_generator = AsyncMock()
    mock_generator.generate_draft.side_effect = RuntimeError("DB timeout")

    with patch(_NOTIFY_FAILURE) as mock_notify:
        mock_notify.return_value = None
        with pytest.raises(RuntimeError):
            await generate_draft_task(
                topic="Мігрень",
                platform="threads",
                generator=mock_generator,
                session=AsyncMock(),
                user_id="U777",
                channel_id="C777",
            )

    mock_notify.assert_awaited_once()
    kwargs = mock_notify.call_args.kwargs
    assert kwargs["user_id"] == "U777"
    assert "DB timeout" in kwargs["error_msg"]
