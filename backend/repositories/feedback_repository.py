from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Feedback
from backend.models.schemas import FeedbackCreate


class FeedbackRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, feedback_in: FeedbackCreate) -> Feedback:
        db_feedback = Feedback(**feedback_in.model_dump())
        self.session.add(db_feedback)
        await self.session.flush()
        await self.session.refresh(db_feedback)
        return db_feedback

    async def get_by_draft_id(self, draft_id: int) -> list[Feedback]:
        stmt = select(Feedback).where(Feedback.draft_id == draft_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
