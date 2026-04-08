"""Handler for Slack slash command payloads."""

import httpx
import structlog
from fastapi import Request
from fastapi.responses import Response

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from slack_app.utils.block_builder import build_generation_modal

logger = structlog.get_logger()


async def handle_slash_command(request: Request) -> dict[str, str] | Response:
    """Dispatch /draft slash command: open generation modal or return ephemeral error."""
    form_data = await request.form()
    command = form_data.get("command")
    trigger_id = form_data.get("trigger_id")
    channel_id = str(form_data.get("channel_id"))

    if command != "/draft":
        return {"response_type": "ephemeral", "text": SLACK_UI["cmd_unknown"]}

    modal_view = build_generation_modal(channel_id=channel_id)
    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/views.open",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"trigger_id": trigger_id, "view": modal_view},
        )
        if not res.json().get("ok"):
            logger.error("slack_modal_open_error", error=res.json())

    return Response(status_code=200)
