from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_feedback_repository
from backend.models.schemas import FeedbackCreate, FeedbackResponse
from backend.repositories.feedback_repository import FeedbackRepository

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback_in: FeedbackCreate,
    feedback_repo: Annotated[FeedbackRepository, Depends(get_feedback_repository)],
):
    """Зберігає відгук користувача щодо згенерованої чернетки."""
    feedback = await feedback_repo.create(feedback_in)
    return feedback
