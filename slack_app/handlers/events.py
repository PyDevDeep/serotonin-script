"""Handler for Slack Events API payloads."""

from typing import Any

import httpx
import structlog
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.repositories.draft_repository import DraftRepository
from slack_app.utils.block_builder import build_app_home

logger = structlog.get_logger()


async def handle_slack_event(
    data: dict[str, Any], session: AsyncSession
) -> dict[str, str] | Response:
    """Dispatch Events API callbacks.

    Returns the challenge dict for url_verification; Response(200) for all others.
    """
    if data.get("type") == "url_verification":
        return {"challenge": str(data.get("challenge", ""))}

    event = data.get("event", {})
    user_id = event.get("user")

    logger.info("slack_event_received", event_type=event.get("type"), user_id=user_id)

    if event.get("type") == "app_home_opened":
        await _handle_app_home_opened(user_id=user_id, session=session)

    return Response(status_code=200)


async def _handle_app_home_opened(user_id: str, session: AsyncSession) -> None:
    repo = DraftRepository(session)
    recent_drafts = await repo.get_recent_drafts(limit=10)

    logger.info("slack_home_opened", user_id=user_id, drafts_count=len(recent_drafts))

    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value()
        if hasattr(settings.SLACK_BOT_TOKEN, "get_secret_value")
        else settings.SLACK_BOT_TOKEN
    )
    home_view = build_app_home(drafts=recent_drafts, offset=0)

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/views.publish",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"user_id": user_id, "view": home_view},
        )
        resp_data = res.json()
        if not resp_data.get("ok"):
            logger.error("slack_home_publish_error", error=resp_data)
        else:
            logger.info("slack_home_published", user_id=user_id)
