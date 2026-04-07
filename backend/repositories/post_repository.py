from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import PublishedPost
from backend.models.schemas import PublishedPostCreate


class PostRepository:
    """Repository for CRUD operations on PublishedPost records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, post_in: PublishedPostCreate) -> PublishedPost:
        """Create and persist a new PublishedPost record."""
        db_post = PublishedPost(**post_in.model_dump())
        self.session.add(db_post)
        await self.session.flush()
        await self.session.refresh(db_post)
        return db_post

    async def get_by_draft_id(self, draft_id: int) -> list[PublishedPost]:
        """Return all PublishedPost records associated with a given draft."""
        stmt = select(PublishedPost).where(PublishedPost.draft_id == draft_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
