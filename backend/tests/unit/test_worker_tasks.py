"""
Tests for remaining worker tasks.

Coverage:
- publish_post_task: success path, publisher exception propagates
- check_scheduled_posts_task: no due drafts, drafts found + enqueued, exception per draft
- vectorize_published_post_task: success, exception propagates
- ingest_guideline_task: success, exception path + Slack failure notification
- generate_draft_task: JudgeFailedError with numeric draft_id saves to DB (line 76-77)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from backend.models.enums import Platform
from backend.services.content_generator import JudgeFailedError
from backend.services.exceptions import PublishingFailedError
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.ingest_guideline import ingest_guideline_task
from backend.workers.tasks.publish_post import publish_post_task
from backend.workers.tasks.scheduled_post import check_scheduled_posts_task
from backend.workers.tasks.vectorize_post import vectorize_published_post_task

# ---------------------------------------------------------------------------
# publish_post_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublishPostTask:
    @pytest.mark.asyncio
    async def test_success_returns_status_dict(self) -> None:
        mock_service = AsyncMock()
        result = await publish_post_task(
            post_id="post-1",
            platform="telegram",
            content="Hello",
            publisher_service=mock_service,
        )
        mock_service.publish.assert_awaited_once_with(
            post_id="post-1", platform="telegram", content="Hello"
        )
        assert result == {
            "status": "success",
            "post_id": "post-1",
            "platform": "telegram",
        }

    @pytest.mark.asyncio
    async def test_publisher_exception_propagates(self) -> None:
        mock_service = AsyncMock()
        mock_service.publish.side_effect = PublishingFailedError(
            Platform.TELEGRAM, "503"
        )

        with pytest.raises(PublishingFailedError):
            await publish_post_task(
                post_id="post-1",
                platform="telegram",
                content="text",
                publisher_service=mock_service,
            )


# ---------------------------------------------------------------------------
# check_scheduled_posts_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckScheduledPostsTask:
    @pytest.mark.asyncio
    async def test_no_due_drafts_returns_early(self) -> None:
        mock_session = AsyncMock()
        with patch(
            "backend.workers.tasks.scheduled_post.DraftRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get_due_scheduled_drafts.return_value = []
            mock_repo_cls.return_value = mock_repo

            await check_scheduled_posts_task(session=mock_session)

        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_due_drafts_enqueued_and_status_updated(self) -> None:
        mock_session = AsyncMock()
        draft = MagicMock()
        draft.id = 5
        draft.platform = "telegram"
        draft.content = "Post content"

        with (
            patch(
                "backend.workers.tasks.scheduled_post.DraftRepository"
            ) as mock_repo_cls,
            patch(
                "backend.workers.tasks.scheduled_post.publish_post_task"
            ) as mock_task,
        ):
            mock_repo = AsyncMock()
            mock_repo.get_due_scheduled_drafts.return_value = [draft]
            mock_repo_cls.return_value = mock_repo
            mock_task.kiq = AsyncMock()

            await check_scheduled_posts_task(session=mock_session)

        mock_task.kiq.assert_awaited_once_with(
            post_id="5", platform="telegram", content="Post content"
        )
        mock_repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_per_draft_logged_continues(self) -> None:
        """If one draft fails to enqueue, processing continues (no re-raise)."""
        mock_session = AsyncMock()
        draft = MagicMock()
        draft.id = 99
        draft.platform = "twitter"
        draft.content = "text"

        with (
            patch(
                "backend.workers.tasks.scheduled_post.DraftRepository"
            ) as mock_repo_cls,
            patch(
                "backend.workers.tasks.scheduled_post.publish_post_task"
            ) as mock_task,
        ):
            mock_repo = AsyncMock()
            mock_repo.get_due_scheduled_drafts.return_value = [draft]
            mock_repo_cls.return_value = mock_repo
            mock_task.kiq = AsyncMock(side_effect=RuntimeError("broker down"))

            # Should not raise — exception is caught per draft
            await check_scheduled_posts_task(session=mock_session)

        mock_repo.update.assert_not_awaited()


# ---------------------------------------------------------------------------
# vectorize_published_post_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVectorizePublishedPostTask:
    @pytest.mark.asyncio
    async def test_success_writes_markdown_and_inserts_to_qdrant(self) -> None:
        with (
            patch("backend.workers.tasks.vectorize_post.Path.mkdir"),
            patch("backend.workers.tasks.vectorize_post.Path.open", mock_open()),
            patch("backend.workers.tasks.vectorize_post.AsyncQdrantClient"),
            patch("backend.workers.tasks.vectorize_post.QdrantVectorStore"),
            patch("backend.workers.tasks.vectorize_post.StorageContext") as mock_ctx,
            patch("backend.workers.tasks.vectorize_post.VectorStoreIndex") as mock_idx,
        ):
            mock_index = AsyncMock()
            mock_idx.from_vector_store.return_value = mock_index
            mock_ctx.from_defaults.return_value = MagicMock()

            await vectorize_published_post_task(
                content="Post text", platform="telegram"
            )

        mock_index.ainsert.assert_awaited_once()
        doc_arg = mock_index.ainsert.call_args.args[0]
        assert doc_arg.text == "Post text"
        assert doc_arg.metadata["platform"] == "telegram"

    @pytest.mark.asyncio
    async def test_exception_propagates(self) -> None:
        with (
            patch("backend.workers.tasks.vectorize_post.Path.mkdir"),
            patch(
                "backend.workers.tasks.vectorize_post.Path.open",
                side_effect=OSError("disk full"),
            ),
        ):
            with pytest.raises(OSError, match="disk full"):
                await vectorize_published_post_task(content="text", platform="twitter")


# ---------------------------------------------------------------------------
# ingest_guideline_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIngestGuidelineTask:
    @pytest.mark.asyncio
    async def test_success_notifies_slack_on_completion(self) -> None:
        from llama_index.core.schema import Document

        mock_doc = MagicMock(spec=Document)
        mock_doc.metadata = {}

        class FakeReader:
            def load_data(self) -> list[Document]:
                return [mock_doc]

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.content = b"PDF content"

        with (
            patch("backend.workers.tasks.ingest_guideline.Path.mkdir"),
            patch("builtins.open", mock_open()),
            patch(
                "backend.workers.tasks.ingest_guideline.httpx.AsyncClient"
            ) as mock_client_cls,
            patch("backend.workers.tasks.ingest_guideline.AsyncQdrantClient"),
            patch("backend.workers.tasks.ingest_guideline.QdrantVectorStore"),
            patch("backend.workers.tasks.ingest_guideline.StorageContext") as mock_ctx,
            patch(
                "backend.workers.tasks.ingest_guideline.VectorStoreIndex"
            ) as mock_idx,
            patch(
                "backend.workers.tasks.ingest_guideline.notify_slack_upload_success"
            ) as mock_notify,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            mock_ctx.from_defaults.return_value = MagicMock()
            mock_index = AsyncMock()
            mock_idx.from_vector_store.return_value = mock_index

            await ingest_guideline_task(
                file_url="https://slack.com/files/file.pdf",
                file_name="guide.pdf",
                user_id="U123",
                reader=FakeReader(),
            )

        mock_notify.assert_awaited_once_with(user_id="U123", file_name="guide.pdf")
        assert mock_doc.metadata["source"] == "guide.pdf"

    @pytest.mark.asyncio
    async def test_exception_notifies_slack_failure_and_reraises(self) -> None:
        with (
            patch("backend.workers.tasks.ingest_guideline.Path.mkdir"),
            patch(
                "backend.workers.tasks.ingest_guideline.httpx.AsyncClient"
            ) as mock_client_cls,
            patch(
                "backend.workers.tasks.ingest_guideline.notify_slack_upload_failure"
            ) as mock_notify,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = RuntimeError("download failed")
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="download failed"):
                await ingest_guideline_task(
                    file_url="https://slack.com/bad",
                    file_name="bad.pdf",
                    user_id="U999",
                )

        mock_notify.assert_awaited_once_with(
            user_id="U999", file_name="bad.pdf", error_msg="download failed"
        )

    @pytest.mark.asyncio
    async def test_exception_without_user_id_no_slack_call(self) -> None:
        with (
            patch("backend.workers.tasks.ingest_guideline.Path.mkdir"),
            patch(
                "backend.workers.tasks.ingest_guideline.httpx.AsyncClient"
            ) as mock_client_cls,
            patch(
                "backend.workers.tasks.ingest_guideline.notify_slack_upload_failure"
            ) as mock_notify,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = RuntimeError("timeout")
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError):
                await ingest_guideline_task(
                    file_url="https://slack.com/file.pdf",
                    file_name="file.pdf",
                    user_id=None,
                )

        mock_notify.assert_not_awaited()


# ---------------------------------------------------------------------------
# generate_draft_task — remaining line 76-77 (JudgeFailedError + numeric draft_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDraftTaskRemainingBranches:
    @pytest.mark.asyncio
    async def test_judge_failure_with_numeric_draft_id_saves_failed_draft_to_db(
        self,
    ) -> None:
        """Lines 75-78: JudgeFailedError + draft_id.isdigit() → repo.update(FAILED)."""
        mock_generator = AsyncMock()
        mock_generator.generate_draft.side_effect = JudgeFailedError(
            topic="Тривога", attempts=2, draft="Відхилений текст"
        )

        with patch(
            "backend.workers.tasks.generate_draft.DraftRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            with pytest.raises(JudgeFailedError):
                await generate_draft_task(
                    topic="Тривога",
                    platform="telegram",
                    generator=mock_generator,
                    session=AsyncMock(),
                    draft_id="10",
                )

        mock_repo.update.assert_awaited_once()
        call_args = mock_repo.update.call_args
        assert call_args.args[0] == 10
        update_payload = call_args.args[1]
        assert update_payload.content == "Відхилений текст"
