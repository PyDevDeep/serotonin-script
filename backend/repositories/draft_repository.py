from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Draft
from backend.models.enums import DraftStatus
from backend.models.schemas import DraftCreate, DraftUpdate


class DraftRepository:
    """Repository for CRUD operations on Draft records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, draft_in: DraftCreate) -> Draft:
        """Create and persist a new Draft record."""
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
        """Return a Draft by primary key, or None if not found."""
        stmt = select(Draft).where(Draft.id == draft_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, draft_id: int, draft_update: DraftUpdate) -> Draft | None:
        """Apply a partial update to a Draft and return the updated record."""
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
        self, limit: int = 10, offset: int = 0, platform: str | None = None
    ) -> list[Draft]:
        """Return recent non-rejected drafts for the Slack dashboard."""
        stmt = (
            select(Draft)
            .where(Draft.status != DraftStatus.REJECTED)
            .order_by(Draft.updated_at.desc())
        )
        if platform:
            stmt = stmt.where(Draft.platform == platform)
        stmt = stmt.limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, draft_id: int) -> bool:
        """Delete a Draft by primary key. Returns True if a record was deleted."""
        draft = await self.get_by_id(draft_id)
        if draft is None:
            return False
        await self.session.delete(draft)
        await self.session.flush()
        return True

    async def get_due_scheduled_drafts(self) -> list[Draft]:
        """Return all scheduled drafts whose publication time has arrived."""
        now = datetime.now(timezone.utc)
        stmt = select(Draft).where(
            Draft.status == "scheduled", Draft.scheduled_at <= now
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
