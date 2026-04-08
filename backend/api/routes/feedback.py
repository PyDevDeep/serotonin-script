"""
Slack Integration router.

This module is intentionally thin: it parses raw HTTP payloads and delegates
all business logic to handlers in slack_app.handlers.
"""

import json

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from backend.models.enums import DraftStatus
from backend.models.schemas import DraftUpdate, PublishError
from backend.repositories.draft_repository import DraftRepository
from backend.workers.dependencies import get_db_session
from slack_app.handlers.events import handle_slack_event
from slack_app.handlers.interactions import (
    dispatch_block_action,
    dispatch_view_submission,
)
from slack_app.handlers.slash_commands import handle_slash_command

logger = structlog.get_logger()
router = APIRouter(prefix="/slack", tags=["Slack Integration"])


@router.post("/commands", response_model=None)
async def slack_slash_command(request: Request) -> dict[str, str] | Response:
    """Handle Slack slash commands and open the draft generation modal."""
    return await handle_slash_command(request)


@router.post("/interactions")
async def slack_interactions(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> Response:
    """Dispatch Slack block_actions and view_submission interaction payloads."""
    form_data = await request.form()
    payload_str = form_data.get("payload")

    if not payload_str:
        raise HTTPException(status_code=400, detail="Missing payload")

    payload = json.loads(str(payload_str))
    interaction_type = payload.get("type")

    if interaction_type == "block_actions":
        return await dispatch_block_action(payload, session)

    if interaction_type == "view_submission":
        return await dispatch_view_submission(payload, session)

    return Response(status_code=200)


@router.post("/error")
async def report_publish_error(
    error: PublishError,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> Response:
    """Receive a publish failure report, update draft status, and notify via Slack."""
    logger.error(
        "publish_error_received",
        post_id=error.post_id,
        platform=error.platform,
        error=error.error_message,
    )

    if error.post_id.isdigit():
        repo = DraftRepository(session)
        await repo.update(int(error.post_id), DraftUpdate(status=DraftStatus.FAILED))

    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    target = error.user_id if error.user_id else settings.SLACK_LOG_CHANNEL

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={
                "channel": target,
                "text": SLACK_UI["publish_error_notification"].format(
                    platform=error.platform.upper(),
                    post_id=error.post_id,
                    error_message=error.error_message,
                ),
            },
        )
        if not res.json().get("ok"):
            logger.error("slack_publish_error_notification_failed", error=res.json())

    return Response(status_code=200)


@router.post("/events", response_model=None)
async def slack_events(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> dict[str, str] | Response:
    """Handle Events API callbacks such as the app_home_opened event."""
    data = await request.json()
    return await handle_slack_event(data, session)
