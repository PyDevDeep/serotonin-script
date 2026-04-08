from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.llm.router import LLMRouter
from backend.models.enums import Platform
from backend.services.publisher_service import PublisherService
from backend.workers.dependencies import (
    get_db_session,
    get_llm_router,
    get_publisher_service,
)

# --- get_db_session (workers variant — mirrors api but uses workers session maker) ---


@pytest.mark.asyncio
async def test_worker_get_db_session_yields_and_commits():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.workers.dependencies.async_session_maker", return_value=mock_ctx
    ):
        gen = get_db_session()
        session = await gen.__anext__()
        assert session is mock_session
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_worker_get_db_session_rollback_on_exception():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.workers.dependencies.async_session_maker", return_value=mock_ctx
    ):
        gen = get_db_session()
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("taskiq error"))

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    mock_session.commit.assert_not_called()


# --- get_llm_router ---


def test_get_llm_router_returns_instance():
    with (
        patch(
            "backend.integrations.llm.router.get_anthropic_llm",
            return_value=MagicMock(),
        ),
        patch(
            "backend.integrations.llm.router.get_openai_llm", return_value=MagicMock()
        ),
        patch(
            "backend.integrations.llm.router.get_cheap_openai_llm",
            return_value=MagicMock(),
        ),
    ):
        router = get_llm_router()
    assert isinstance(router, LLMRouter)


def test_get_llm_router_creates_new_instance_each_call():
    with (
        patch(
            "backend.integrations.llm.router.get_anthropic_llm",
            return_value=MagicMock(),
        ),
        patch(
            "backend.integrations.llm.router.get_openai_llm", return_value=MagicMock()
        ),
        patch(
            "backend.integrations.llm.router.get_cheap_openai_llm",
            return_value=MagicMock(),
        ),
    ):
        r1 = get_llm_router()
        r2 = get_llm_router()
    assert r1 is not r2


# --- get_publisher_service ---


def test_get_publisher_service_returns_instance():
    with patch("backend.workers.dependencies.settings") as mock_settings:
        mock_settings.N8N_WEBHOOK_URL = "http://n8n.local/webhook"
        service = get_publisher_service()
    assert isinstance(service, PublisherService)


def test_get_publisher_service_has_publisher_per_platform():
    with patch("backend.workers.dependencies.settings") as mock_settings:
        mock_settings.N8N_WEBHOOK_URL = "http://n8n.local/webhook"
        service = get_publisher_service()
    for platform in Platform:
        assert platform in service._publishers
