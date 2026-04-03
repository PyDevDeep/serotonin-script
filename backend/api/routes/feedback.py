import json
from typing import cast

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.publish_post import publish_post_task
from slack_app.utils.block_builder import build_approval_modal

logger = structlog.get_logger()
router = APIRouter(prefix="/slack", tags=["Slack Integration"])


@router.post("/commands")
async def slack_slash_command(request: Request):
    form_data = await request.form()
    command = form_data.get("command")
    text = str(form_data.get("text", "")).strip()
    user_id = cast(str, form_data.get("user_id", ""))
    channel_id = cast(str, form_data.get("channel_id", ""))

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

    await generate_draft_task.kiq(  # type: ignore[call-overload]
        topic=topic, platform=platform, user_id=user_id, channel_id=channel_id
    )

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
    interaction_type = payload.get("type")

    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    headers = {"Authorization": f"Bearer {slack_token}"}

    if interaction_type == "block_actions":
        response_url = payload.get("response_url")
        trigger_id = payload.get("trigger_id")
        action = payload.get("actions", [])[0]
        action_id = action.get("action_id")

        blocks = payload.get("message", {}).get("blocks", [])
        raw_draft = blocks[1]["text"]["text"] if len(blocks) > 1 else ""
        draft_text = raw_draft.replace("```", "").strip()
        topic = "Медичний пост"

        if action_id == "action_publish_draft":
            logger.info("slack_draft_approved", user_id=user_id)
            await publish_post_task.kiq(
                post_id="temp_id", platform="telegram", content=draft_text
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
            logger.info("slack_draft_rejected", user_id=user_id)
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

        elif action_id == "action_edit_draft":
            logger.info("slack_draft_edit_opened", user_id=user_id)
            modal_view = build_approval_modal(
                topic=topic, draft=draft_text, platform="telegram"
            )
            async with httpx.AsyncClient() as client:
                # ВИПРАВЛЕНО URL
                res = await client.post(
                    "[https://slack.com/api/views.open](https://slack.com/api/views.open)",
                    headers=headers,
                    json={"trigger_id": trigger_id, "view": modal_view},
                )
                if not res.json().get("ok"):
                    logger.error("slack_modal_error", error=res.json())

        elif action_id == "action_regenerate_draft":
            logger.info("slack_draft_regenerate", user_id=user_id)
            channel_id = payload.get("channel", {}).get("id")  # ДОДАНО

            await generate_draft_task.kiq(  # type: ignore[call-overload]
                topic=topic, platform="telegram", user_id=user_id, channel_id=channel_id
            )

            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={
                        "replace_original": True,
                        "text": SLACK_UI["interact_regenerate_text"],
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": SLACK_UI["interact_regenerate_section"],
                                },
                            }
                        ],
                    },
                )

        return Response(status_code=200)

    elif interaction_type == "view_submission":
        view = payload.get("view", {})
        state_values = view.get("state", {}).get("values", {})

        draft_content = (
            state_values.get("block_draft_content", {})
            .get("input_draft_content", {})
            .get("value", "")
        )
        platform = (
            state_values.get("block_platform_select", {})
            .get("input_platform_select", {})
            .get("selected_option", {})
            .get("value", "telegram")
        )

        logger.info("slack_modal_submitted", user_id=user_id, platform=platform)

        await publish_post_task.kiq(
            post_id="temp_id", platform=platform, content=draft_content
        )

        return Response(
            content=json.dumps({"response_action": "clear"}),
            media_type="application/json",
            status_code=200,
        )

    return Response(status_code=200)
