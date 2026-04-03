from typing import Any

import httpx
import structlog

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings

logger = structlog.get_logger()

SLACK_API_URL = "https://slack.com/api/chat.postMessage"


async def _send_slack_message(payload: dict[str, Any]) -> None:
    token = (
        settings.SLACK_BOT_TOKEN.get_secret_value()
        if settings.SLACK_BOT_TOKEN
        else None
    )
    if not token:
        logger.error("slack_token_missing", action="aborting_notification")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(SLACK_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logger.error(
                    "slack_api_error", error=data.get("error"), payload=payload
                )
        except Exception as e:
            logger.error(
                "slack_network_error", error=str(e), error_type=type(e).__name__
            )


async def notify_slack_on_complete(
    user_id: str, channel_id: str, draft: str, topic: str
) -> None:
    logger.info(
        "sending_slack_completion_notification", user_id=user_id, channel_id=channel_id
    )

    payload = {
        "channel": channel_id,
        "text": SLACK_UI["draft_ready_fallback"].format(topic=topic),
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": SLACK_UI["draft_ready_header"].format(topic=topic),
                    "emoji": True,
                },
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": f"```{draft}```"}},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": SLACK_UI["ordered_by"].format(user_id=user_id),
                    }
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": SLACK_UI["btn_publish"],
                            "emoji": True,
                        },
                        "style": "primary",
                        "value": "publish",
                        "action_id": "action_publish_draft",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": SLACK_UI["btn_reject"],
                            "emoji": True,
                        },
                        "style": "danger",
                        "value": "reject",
                        "action_id": "action_reject_draft",
                    },
                ],
            },
        ],
    }
    await _send_slack_message(payload)


async def notify_slack_on_failure(
    user_id: str, channel_id: str, error_msg: str, topic: str
) -> None:
    logger.info(
        "sending_slack_failure_notification", user_id=user_id, channel_id=channel_id
    )

    payload = {
        "channel": channel_id,
        "text": SLACK_UI["error_fallback"].format(topic=topic),
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": SLACK_UI["error_header"],
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": SLACK_UI["error_details"].format(
                        topic=topic, user_id=user_id, error_msg=error_msg
                    ),
                },
            },
        ],
    }
    await _send_slack_message(payload)
