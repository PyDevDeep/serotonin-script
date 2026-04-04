from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Draft
from backend.models.schemas import DraftCreate, DraftUpdate


class DraftRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, draft_in: DraftCreate) -> Draft:
        db_draft = Draft(
            user_id=draft_in.user_id,
            topic=draft_in.topic,
            status="pending",
            platform=draft_in.platform,
        )
        self.session.add(db_draft)
        await self.session.flush()
        await self.session.refresh(db_draft)
        return db_draft

    async def get_by_id(self, draft_id: int) -> Draft | None:
        stmt = select(Draft).where(Draft.id == draft_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, draft_id: int, draft_update: DraftUpdate) -> Draft | None:
        update_data = draft_update.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_by_id(draft_id)

        stmt = (
            update(Draft)
            .where(Draft.id == draft_id)
            .values(**update_data)
            .returning(Draft)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_recent_drafts(
        self, limit: int = 10, platform: str | None = None
    ) -> list[Draft]:
        """Витягує останні драфти (для Дашборду в Slack)"""
        stmt = select(Draft).order_by(Draft.updated_at.desc())
        if platform:
            stmt = stmt.where(Draft.platform == platform)
        stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_due_scheduled_drafts(self) -> list[Draft]:
        """Витягує всі пости, час яких настав, але вони ще не опубліковані (для Планувальника)"""
        now = datetime.now(timezone.utc)
        stmt = select(Draft).where(
            Draft.status == "scheduled", Draft.scheduled_at <= now
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
