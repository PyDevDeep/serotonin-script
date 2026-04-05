import asyncio
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.dependencies import get_draft_repository
from backend.models.schemas import (
    DraftCreate,
    DraftGenerateRequest,
    DraftResponse,
    PublishConfirmPayload,
    TaskResponse,
)
from backend.repositories.draft_repository import DraftRepository
from backend.workers.broker import result_backend
from backend.workers.tasks.generate_draft import generate_draft_task

logger = structlog.get_logger()
router = APIRouter(prefix="/draft", tags=["Drafts"])


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    request: DraftGenerateRequest,
    draft_repo: Annotated[DraftRepository, Depends(get_draft_repository)],
):
    """
    1. Створює новий запис у БД.
    2. Відправляє фонову задачу генерації в Taskiq.
    3. Повертає task_id клієнту.
    """
    draft_in = DraftCreate(
        topic=request.topic, user_id=request.user_id, platform=request.platform
    )
    await draft_repo.create(draft_in)

    # Викликаємо фонову задачу
    task: Any = await generate_draft_task.kiq(  # type: ignore[reportCallIssue]
        topic=request.topic,
        platform=request.platform.value,
        source_url=request.source_url,
    )
    # TODO у майбутньому: оновити draft у БД, додавши йому task_id
    return TaskResponse(
        task_id=str(task.task_id),  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        status="QUEUED",
    )


@router.get("/{task_id}/status", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """Перевіряє поточний статус задачі без блокування."""
    is_ready = await result_backend.is_result_ready(task_id)

    if not is_ready:
        return TaskResponse(task_id=task_id, status="PENDING")

    result = await result_backend.get_result(task_id)
    status_val = "FAILED" if result.is_err else "COMPLETED"
    return TaskResponse(task_id=task_id, status=status_val)


@router.get("/{task_id}/result", response_model=TaskResponse)
async def get_task_result(task_id: str):
    """
    Чекає на результат задачі (до 30 секунд).
    Використовується для Long Polling з боку n8n/Slack.
    """
    timeout = 30

    for _ in range(timeout):
        if await result_backend.is_result_ready(task_id):
            result = await result_backend.get_result(task_id)
            if result.is_err:
                return TaskResponse(
                    task_id=task_id, status="FAILED", error=str(result.error)
                )
            return TaskResponse(
                task_id=task_id, status="COMPLETED", result=result.return_value
            )
        await asyncio.sleep(1)

    return TaskResponse(task_id=task_id, status="TIMEOUT_OR_PENDING")


@router.get("/db/{draft_id}", response_model=DraftResponse)
async def get_draft_from_db(
    draft_id: int, draft_repo: Annotated[DraftRepository, Depends(get_draft_repository)]
):
    """Повертає статус та контент чернетки безпосередньо з БД."""
    draft = await draft_repo.get_by_id(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    return draft


@router.post("/webhook/n8n-publish-confirm", status_code=status.HTTP_200_OK)
async def n8n_publish_confirmation(
    payload: PublishConfirmPayload,
    draft_repo: Annotated[DraftRepository, Depends(get_draft_repository)],
):
    """
    Webhook для n8n. Викликається ПІСЛЯ успішної публікації в соцмережах.
    """
    logger.info(
        "n8n_publish_confirmed", post_id=payload.post_id, platform=payload.platform
    )

    # 1. Оновлюємо статус у БД (якщо це не наша хардкодна заглушка)
    if payload.post_id and payload.post_id != "temp_id":
        try:
            # Припускаємо, що у тебе є метод update_status (або реалізуй його)
            # await draft_repo.update_status(int(payload.post_id), "PUBLISHED")
            pass
        except Exception as e:
            logger.error("db_update_failed", error=str(e))

    # 2. Запускаємо фонову задачу векторизації
    # Щоб не блокувати API, відправляємо текст у Taskiq
    from backend.workers.tasks.vectorize_post import vectorize_published_post_task

    await vectorize_published_post_task.kiq(
        content=payload.content, platform=payload.platform
    )

    return {"status": "success", "message": "Post ingested into knowledge base"}
