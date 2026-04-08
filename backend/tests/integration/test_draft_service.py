"""
Integration tests for backend.services.draft_service.DraftService.

Strategy: SQLite in-memory via aiosqlite — no Docker, no external services.
SQLAlchemy creates the schema from ORM models before each test and drops it after.
Taskiq broker calls (.kiq) are patched to prevent real task dispatch.

Coverage targets (draft_service.py lines 18-79):
- get_or_create_user: creates new user, returns existing user
- generate_draft_from_slack: creates draft + enqueues generate_draft_task
- process_manual_post: immediate publish path, scheduled path
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.db_models import Base
from backend.models.enums import DraftStatus, Platform
from backend.services.draft_service import DraftService

# ---------------------------------------------------------------------------
# Engine + schema fixtures
# ---------------------------------------------------------------------------

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory SQLite engine and build the full schema."""
    eng = create_async_engine(DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession that rolls back after each test."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


@pytest.fixture
def service(session: AsyncSession) -> DraftService:
    return DraftService(session=session)


# ---------------------------------------------------------------------------
# get_or_create_user
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetOrCreateUser:
    @pytest.mark.asyncio
    async def test_creates_new_user(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        user = await service.get_or_create_user("slack_user_1")
        await session.commit()

        assert user.id is not None
        assert user.username == "slack_user_1"

    @pytest.mark.asyncio
    async def test_returns_existing_user_on_second_call(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        user_first = await service.get_or_create_user("slack_user_2")
        await session.commit()

        user_second = await service.get_or_create_user("slack_user_2")
        await session.commit()

        assert user_first.id == user_second.id

    @pytest.mark.asyncio
    async def test_different_users_get_different_ids(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        a = await service.get_or_create_user("user_a")
        b = await service.get_or_create_user("user_b")
        await session.commit()

        assert a.id != b.id


# ---------------------------------------------------------------------------
# generate_draft_from_slack
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGenerateDraftFromSlack:
    @pytest.mark.asyncio
    async def test_creates_draft_and_returns_id(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        with patch("backend.services.draft_service.generate_draft_task") as mock_task:
            mock_task.kiq = AsyncMock()
            draft_id = await service.generate_draft_from_slack(
                user_id="U001",
                topic="Anxiety disorders",
                platform=Platform.TELEGRAM,
                channel_id="C001",
            )
            await session.commit()

        assert draft_id.isdigit()

    @pytest.mark.asyncio
    async def test_enqueues_generate_task_with_correct_args(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        with patch("backend.services.draft_service.generate_draft_task") as mock_task:
            mock_task.kiq = AsyncMock()
            draft_id = await service.generate_draft_from_slack(
                user_id="U002",
                topic="Depression treatment",
                platform=Platform.TWITTER,
                channel_id="C002",
            )
            await session.commit()

        mock_task.kiq.assert_awaited_once()
        kiq_kwargs = mock_task.kiq.call_args.kwargs
        assert kiq_kwargs["topic"] == "Depression treatment"
        assert kiq_kwargs["platform"] == "twitter"
        assert kiq_kwargs["user_id"] == "U002"
        assert kiq_kwargs["channel_id"] == "C002"
        assert kiq_kwargs["draft_id"] == draft_id

    @pytest.mark.asyncio
    async def test_reuses_existing_user(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        with patch("backend.services.draft_service.generate_draft_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.generate_draft_from_slack(
                "U003", "topic", Platform.TELEGRAM, "C"
            )
            await service.generate_draft_from_slack(
                "U003", "topic2", Platform.TELEGRAM, "C"
            )
            await session.commit()

        # Two drafts created, one user
        assert mock_task.kiq.await_count == 2


# ---------------------------------------------------------------------------
# process_manual_post — immediate publish
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProcessManualPostImmediate:
    @pytest.mark.asyncio
    async def test_immediate_publish_enqueues_publish_task(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        with patch("backend.services.draft_service.publish_post_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.process_manual_post(
                user_id="U010",
                content="My post content",
                platform=Platform.TELEGRAM,
                scheduled_at=None,
            )
            await session.commit()

        mock_task.kiq.assert_awaited_once()
        kiq_kwargs = mock_task.kiq.call_args.kwargs
        assert kiq_kwargs["platform"] == "telegram"
        assert kiq_kwargs["content"] == "My post content"

    @pytest.mark.asyncio
    async def test_immediate_publish_sets_published_status(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from backend.models.db_models import Draft

        with patch("backend.services.draft_service.publish_post_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.process_manual_post(
                user_id="U011",
                content="Content here",
                platform=Platform.TWITTER,
                scheduled_at=None,
            )
            await session.commit()

        result = await session.execute(select(Draft).order_by(Draft.id.desc()).limit(1))
        draft = result.scalar_one()
        assert draft.status == DraftStatus.PUBLISHED

    @pytest.mark.asyncio
    async def test_topic_truncated_to_80_chars(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from backend.models.db_models import Draft

        long_content = "A" * 200

        with patch("backend.services.draft_service.publish_post_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.process_manual_post(
                user_id="U012",
                content=long_content,
                platform=Platform.THREADS,
                scheduled_at=None,
            )
            await session.commit()

        result = await session.execute(select(Draft).order_by(Draft.id.desc()).limit(1))
        draft = result.scalar_one()
        assert len(draft.topic) == 80


# ---------------------------------------------------------------------------
# process_manual_post — scheduled
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProcessManualPostScheduled:
    @pytest.mark.asyncio
    async def test_scheduled_post_sets_scheduled_status(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from backend.models.db_models import Draft

        future = datetime.now(timezone.utc) + timedelta(hours=2)

        with patch("backend.services.draft_service.publish_post_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.process_manual_post(
                user_id="U020",
                content="Scheduled content",
                platform=Platform.TELEGRAM,
                scheduled_at=future,
            )
            await session.commit()

        result = await session.execute(select(Draft).order_by(Draft.id.desc()).limit(1))
        draft = result.scalar_one()
        assert draft.status == DraftStatus.SCHEDULED
        assert draft.content == "Scheduled content"

    @pytest.mark.asyncio
    async def test_scheduled_post_does_not_enqueue_publish_task(
        self, service: DraftService, session: AsyncSession
    ) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch("backend.services.draft_service.publish_post_task") as mock_task:
            mock_task.kiq = AsyncMock()
            await service.process_manual_post(
                user_id="U021",
                content="Later post",
                platform=Platform.TWITTER,
                scheduled_at=future,
            )
            await session.commit()

        mock_task.kiq.assert_not_awaited()
