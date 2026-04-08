from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import (
    get_db_session,
    get_draft_repository,
    get_feedback_repository,
)
from backend.repositories.draft_repository import DraftRepository
from backend.repositories.feedback_repository import FeedbackRepository

# --- get_db_session ---


@pytest.mark.asyncio
async def test_get_db_session_yields_and_commits():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.api.dependencies.async_session_maker", return_value=mock_ctx):
        gen = get_db_session()
        session = await gen.__anext__()
        assert session is mock_session
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_session_rollback_on_exception():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.api.dependencies.async_session_maker", return_value=mock_ctx):
        gen = get_db_session()
        session = await gen.__anext__()
        assert session is mock_session
        with pytest.raises(ValueError):
            await gen.athrow(ValueError("db error"))

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_db_session_close_called_even_on_rollback_error():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.rollback.side_effect = RuntimeError("rollback failed")
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.api.dependencies.async_session_maker", return_value=mock_ctx):
        gen = get_db_session()
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(ValueError("trigger rollback"))

    mock_session.close.assert_called_once()


# --- get_draft_repository ---


def test_get_draft_repository_returns_instance():
    mock_session = MagicMock(spec=AsyncSession)
    repo = get_draft_repository(mock_session)
    assert isinstance(repo, DraftRepository)


def test_get_draft_repository_uses_session():
    mock_session = MagicMock(spec=AsyncSession)
    repo = get_draft_repository(mock_session)
    assert repo.session is mock_session


# --- get_feedback_repository ---


def test_get_feedback_repository_returns_instance():
    mock_session = MagicMock(spec=AsyncSession)
    repo = get_feedback_repository(mock_session)
    assert isinstance(repo, FeedbackRepository)


def test_get_feedback_repository_uses_session():
    mock_session = MagicMock(spec=AsyncSession)
    repo = get_feedback_repository(mock_session)
    assert repo.session is mock_session
