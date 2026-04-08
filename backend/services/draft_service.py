from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import User
from backend.models.enums import DraftStatus, Platform
from backend.models.schemas import DraftCreate, DraftUpdate
from backend.repositories.draft_repository import DraftRepository
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.publish_post import publish_post_task


class DraftService:
    """Application service for orchestrating draft operations and queue dispatches."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DraftRepository(session)

    async def get_or_create_user(self, user_id: str) -> User:
        user_query = await self.session.execute(
            select(User).where(User.username == user_id)
        )
        db_user = user_query.scalar_one_or_none()
        if not db_user:
            db_user = User(username=user_id)
            self.session.add(db_user)
            await self.session.flush()
        return db_user

    async def generate_draft_from_slack(
        self,
        user_id: str,
        topic: str,
        platform: Platform,
        channel_id: str,
        source_url: str | None = None,
    ) -> str:
        db_user = await self.get_or_create_user(user_id)

        new_draft = await self.repo.create(
            DraftCreate(topic=topic, platform=platform, user_id=db_user.id)
        )
        real_draft_id = str(new_draft.id)

        await generate_draft_task.kiq(  # type: ignore[call-overload]
            topic=topic,
            platform=platform.value,
            source_url=source_url,
            user_id=user_id,
            channel_id=channel_id,
            draft_id=real_draft_id,
        )
        return real_draft_id

    async def process_manual_post(
        self,
        user_id: str,
        content: str,
        platform: Platform,
        scheduled_at: datetime | None,
    ) -> None:
        db_user = await self.get_or_create_user(user_id)
        topic = content[:80]

        new_draft = await self.repo.create(
            DraftCreate(topic=topic, platform=platform, user_id=db_user.id)
        )

        if scheduled_at:
            await self.repo.update(
                new_draft.id,
                DraftUpdate(
                    content=content,
                    status=DraftStatus.SCHEDULED,
                    scheduled_at=scheduled_at,
                ),
            )
        else:
            await self.repo.update(
                new_draft.id,
                DraftUpdate(content=content, status=DraftStatus.PUBLISHED),
            )
            await publish_post_task.kiq(  # type: ignore[call-overload]
                post_id=str(new_draft.id), platform=platform.value, content=content
            )
