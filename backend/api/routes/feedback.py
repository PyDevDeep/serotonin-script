import json

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from backend.config.lexicon import SLACK_UI
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.publish_post import publish_post_task

logger = structlog.get_logger()
router = APIRouter(prefix="/slack", tags=["Slack Integration"])


@router.post("/commands")
async def slack_slash_command(request: Request):
    """
    Обробляє слеш-команду /draft від Slack.
    Формат очікуваного тексту: "Тема публікації | платформа"
    """
    form_data = await request.form()

    command = form_data.get("command")
    text = str(form_data.get("text", "")).strip()
    user_id = form_data.get("user_id")
    channel_id = form_data.get("channel_id")

    if command != "/draft":
        return {"response_type": "ephemeral", "text": SLACK_UI["cmd_unknown"]}

    if not text:
        return {"response_type": "ephemeral", "text": SLACK_UI["cmd_missing_args"]}

    parts = [p.strip() for p in text.split("|")]
    topic = parts[0]
    platform = parts[1].lower() if len(parts) > 1 else "telegram"

    valid_platforms = ["telegram", "twitter", "threads"]
    if platform not in valid_platforms:
        return {
            "response_type": "ephemeral",
            "text": SLACK_UI["cmd_invalid_platform"].format(
                platform=platform, valid_platforms=", ".join(valid_platforms)
            ),
        }

    logger.info(
        "slack_command_received", topic=topic, platform=platform, user_id=user_id
    )

    # Відправляємо задачу в Taskiq
    await generate_draft_task.kiq(
        topic=topic, platform=platform, user_id=user_id, channel_id=channel_id
    )  # type: ignore[call-overload]

    # Повертаємо миттєву відповідь для Slack
    return {
        "response_type": "in_channel",
        "text": SLACK_UI["cmd_accepted"].format(topic=topic, platform=platform),
    }


@router.post("/interactions")
async def slack_interactions(request: Request):
    form_data = await request.form()
    payload_str = form_data.get("payload")

    if not payload_str:
        raise HTTPException(status_code=400, detail="Missing payload")

    payload = json.loads(str(payload_str))
    user_id = payload.get("user", {}).get("id")
    response_url = payload.get("response_url")

    if payload.get("type") == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            action_id = action.get("action_id")

            if action_id == "action_publish_draft":
                logger.info("slack_draft_approved_button", user_id=user_id)

                # TODO: Витягнути реальний контент з payload/DB
                await publish_post_task.kiq(
                    post_id="temp_id",
                    platform="telegram",
                    content="Згенерований контент",
                )

                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={
                            "replace_original": True,
                            "text": SLACK_UI["interact_approved_text"],
                            "blocks": [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": SLACK_UI["interact_approved_section"],
                                    },
                                }
                            ],
                        },
                    )

            elif action_id == "action_reject_draft":
                logger.info("slack_draft_rejected_button", user_id=user_id)

                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={
                            "replace_original": True,
                            "text": SLACK_UI["interact_rejected_text"],
                            "blocks": [
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": SLACK_UI["interact_rejected_section"],
                                    },
                                }
                            ],
                        },
                    )

    return Response(status_code=200)
