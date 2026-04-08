"""
Tests for backend.repositories.post_repository and feedback_repository.

Strategy:
- AsyncSession is mocked via unittest.mock.AsyncMock / MagicMock.
- execute() returns a mock whose scalars().all() chain is fully controlled.
- flush() and refresh() are AsyncMocks so await calls resolve.
- No real DB required for these unit tests.
  For integration coverage, see backend/tests/integration/test_draft_service.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.db_models import Feedback, PublishedPost
from backend.models.enums import Platform
from backend.models.schemas import FeedbackCreate, PublishedPostCreate
from backend.repositories.feedback_repository import FeedbackRepository
from backend.repositories.post_repository import PostRepository

# ---------------------------------------------------------------------------
# Shared session factory
# ---------------------------------------------------------------------------


def make_session() -> MagicMock:
    """Return a MagicMock that satisfies AsyncSession's async interface."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# PostRepository
# ---------------------------------------------------------------------------


class TestPostRepositoryCreate:
    """Tests for PostRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_adds_post_to_session(self) -> None:
        session = make_session()
        post_in = PublishedPostCreate(
            draft_id=1, platform=Platform.TELEGRAM, post_url="https://t.me/x"
        )

        repo = PostRepository(session)
        await repo.create(post_in)

        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, PublishedPost)

    @pytest.mark.asyncio
    async def test_create_calls_flush_then_refresh(self) -> None:
        session = make_session()
        post_in = PublishedPostCreate(
            draft_id=2, platform=Platform.THREADS, post_url="https://threads.net/x"
        )

        repo = PostRepository(session)
        await repo.create(post_in)

        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_maps_fields_from_schema(self) -> None:
        session = make_session()
        post_in = PublishedPostCreate(
            draft_id=42, platform=Platform.TELEGRAM, post_url="https://t.me/abc"
        )

        repo = PostRepository(session)
        await repo.create(post_in)

        added_obj: PublishedPost = session.add.call_args[0][0]
        assert added_obj.draft_id == 42
        assert added_obj.platform == "telegram"
        assert added_obj.post_url == "https://t.me/abc"

    @pytest.mark.asyncio
    async def test_create_returns_refreshed_object(self) -> None:
        session = make_session()
        post_in = PublishedPostCreate(
            draft_id=1, platform=Platform.TELEGRAM, post_url="https://t.me/y"
        )

        # refresh() populates id on the object — simulate by mutating via side_effect
        async def fake_refresh(obj: PublishedPost) -> None:
            obj.id = 99

        session.refresh.side_effect = fake_refresh

        repo = PostRepository(session)
        result = await repo.create(post_in)

        assert result.id == 99

    @pytest.mark.asyncio
    async def test_create_propagates_flush_exception(self) -> None:
        session = make_session()
        session.flush = AsyncMock(side_effect=RuntimeError("DB constraint violation"))
        post_in = PublishedPostCreate(
            draft_id=1, platform=Platform.TELEGRAM, post_url="https://t.me/z"
        )

        repo = PostRepository(session)
        with pytest.raises(RuntimeError, match="DB constraint violation"):
            await repo.create(post_in)


class TestPostRepositoryGetByDraftId:
    """Tests for PostRepository.get_by_draft_id()."""

    def _mock_execute_result(self, session: MagicMock, rows: list[MagicMock]) -> None:
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result_mock)

    @pytest.mark.asyncio
    async def test_returns_list_of_posts(self) -> None:
        session = make_session()
        post = MagicMock(spec=PublishedPost)
        self._mock_execute_result(session, [post])

        repo = PostRepository(session)
        result = await repo.get_by_draft_id(1)

        assert result == [post]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_posts(self) -> None:
        session = make_session()
        self._mock_execute_result(session, [])

        repo = PostRepository(session)
        result = await repo.get_by_draft_id(999)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_multiple_posts_for_same_draft(self) -> None:
        session = make_session()
        posts = [MagicMock(spec=PublishedPost) for _ in range(3)]
        self._mock_execute_result(session, posts)

        repo = PostRepository(session)
        result = await repo.get_by_draft_id(5)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_executes_select_statement(self) -> None:
        session = make_session()
        self._mock_execute_result(session, [])

        repo = PostRepository(session)
        await repo.get_by_draft_id(7)

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagates_db_exception(self) -> None:
        session = make_session()
        session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        repo = PostRepository(session)
        with pytest.raises(RuntimeError, match="connection lost"):
            await repo.get_by_draft_id(1)


# ---------------------------------------------------------------------------
# FeedbackRepository
# ---------------------------------------------------------------------------


class TestFeedbackRepositoryCreate:
    """Tests for FeedbackRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_adds_feedback_to_session(self) -> None:
        session = make_session()
        feedback_in = FeedbackCreate(draft_id=1, user_id=10, comment="Great post!")

        repo = FeedbackRepository(session)
        await repo.create(feedback_in)

        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, Feedback)

    @pytest.mark.asyncio
    async def test_create_calls_flush_then_refresh(self) -> None:
        session = make_session()
        feedback_in = FeedbackCreate(draft_id=2, user_id=5, comment="Needs improvement")

        repo = FeedbackRepository(session)
        await repo.create(feedback_in)

        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_maps_all_fields_from_schema(self) -> None:
        session = make_session()
        feedback_in = FeedbackCreate(draft_id=3, user_id=7, comment="Excellent!")

        repo = FeedbackRepository(session)
        await repo.create(feedback_in)

        added_obj: Feedback = session.add.call_args[0][0]
        assert added_obj.draft_id == 3
        assert added_obj.user_id == 7
        assert added_obj.comment == "Excellent!"

    @pytest.mark.asyncio
    async def test_create_returns_refreshed_feedback_object(self) -> None:
        session = make_session()

        async def fake_refresh(obj: Feedback) -> None:
            obj.id = 55

        session.refresh.side_effect = fake_refresh
        feedback_in = FeedbackCreate(draft_id=1, user_id=1, comment="ok")

        repo = FeedbackRepository(session)
        result = await repo.create(feedback_in)

        assert result.id == 55

    @pytest.mark.asyncio
    async def test_create_propagates_flush_exception(self) -> None:
        session = make_session()
        session.flush = AsyncMock(side_effect=RuntimeError("FK violation"))
        feedback_in = FeedbackCreate(
            draft_id=9999, user_id=1, comment="orphan feedback"
        )

        repo = FeedbackRepository(session)
        with pytest.raises(RuntimeError, match="FK violation"):
            await repo.create(feedback_in)

    @pytest.mark.asyncio
    async def test_create_empty_comment_is_accepted(self) -> None:
        """FeedbackRepository does not validate comment content — that's the schema's job."""
        session = make_session()
        feedback_in = FeedbackCreate(draft_id=1, user_id=1, comment="")

        repo = FeedbackRepository(session)
        await repo.create(feedback_in)

        added_obj: Feedback = session.add.call_args[0][0]
        assert added_obj.comment == ""


class TestFeedbackRepositoryGetByDraftId:
    """Tests for FeedbackRepository.get_by_draft_id()."""

    def _mock_execute_result(self, session: MagicMock, rows: list[MagicMock]) -> None:
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result_mock)

    @pytest.mark.asyncio
    async def test_returns_list_of_feedback(self) -> None:
        session = make_session()
        fb = MagicMock(spec=Feedback)
        self._mock_execute_result(session, [fb])

        repo = FeedbackRepository(session)
        result = await repo.get_by_draft_id(1)

        assert result == [fb]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_feedback(self) -> None:
        session = make_session()
        self._mock_execute_result(session, [])

        repo = FeedbackRepository(session)
        result = await repo.get_by_draft_id(99)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_feedback_for_draft(self) -> None:
        session = make_session()
        feedbacks = [MagicMock(spec=Feedback) for _ in range(4)]
        self._mock_execute_result(session, feedbacks)

        repo = FeedbackRepository(session)
        result = await repo.get_by_draft_id(10)

        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_executes_query_against_session(self) -> None:
        session = make_session()
        self._mock_execute_result(session, [])

        repo = FeedbackRepository(session)
        await repo.get_by_draft_id(2)

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagates_db_exception(self) -> None:
        session = make_session()
        session.execute = AsyncMock(side_effect=RuntimeError("timeout"))

        repo = FeedbackRepository(session)
        with pytest.raises(RuntimeError, match="timeout"):
            await repo.get_by_draft_id(1)
