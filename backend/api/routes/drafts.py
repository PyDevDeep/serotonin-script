from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies import get_draft_repository
from backend.models.schemas import DraftCreate, DraftResponse
from backend.repositories.draft_repository import DraftRepository

router = APIRouter(prefix="/draft", tags=["Drafts"])


@router.post("/", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    draft_in: DraftCreate,
    draft_repo: Annotated[DraftRepository, Depends(get_draft_repository)],
):
    """
    Створює новий запит на генерацію чернетки.
    (У Phase 4 тут буде виклик Taskiq worker-а).
    """
    # TODO: Додати перевірку чи існує user_id у таблиці users
    draft = await draft_repo.create(draft_in)
    return draft


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: int, draft_repo: Annotated[DraftRepository, Depends(get_draft_repository)]
):
    """Повертає статус та контент чернетки за ID."""
    draft = await draft_repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    return draft
