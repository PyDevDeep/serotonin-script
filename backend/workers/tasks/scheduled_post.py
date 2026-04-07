import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from backend.models.enums import DraftStatus
from backend.models.schemas import DraftUpdate
from backend.repositories.draft_repository import DraftRepository
from backend.workers.broker import broker
from backend.workers.dependencies import get_db_session
from backend.workers.tasks.publish_post import publish_post_task

logger = structlog.get_logger()


@broker.task(task_name="check_scheduled_posts", schedule=[{"cron": "* * * * *"}])
async def check_scheduled_posts_task(
    session: AsyncSession = TaskiqDepends(get_db_session),  # noqa: B008
) -> None:
    """
    Періодична задача, яка перевіряє БД на наявність постів,
    час публікації яких настав.
    """
    repo = DraftRepository(session)

    # Fetch all posts where status == 'scheduled' and scheduled_at <= now
    due_drafts = await repo.get_due_scheduled_drafts()

    if not due_drafts:
        return

    logger.info("found_scheduled_drafts", count=len(due_drafts))

    for draft in due_drafts:
        try:
            # 1. Enqueue for publication
            await publish_post_task.kiq(  # type: ignore[call-overload]
                post_id=str(draft.id),
                platform=draft.platform,
                content=draft.content or "",
            )

            # Update status in DB
            await repo.update(draft.id, DraftUpdate(status=DraftStatus.PUBLISHED))
            logger.info(
                "scheduled_draft_sent_to_publish",
                draft_id=draft.id,
                platform=draft.platform,
            )

        except Exception as e:
            logger.error(
                "failed_to_process_scheduled_draft", draft_id=draft.id, error=str(e)
            )
