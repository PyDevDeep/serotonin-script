"""
Handlers for Slack interaction payloads (block_actions and view_submission).

Each block_action is a standalone async function registered in BLOCK_ACTION_HANDLERS.
Each view_submission callback_id maps to a standalone async function in VIEW_HANDLERS.
Both dicts are the single source of truth — adding a new action requires only a new
function + one dict entry, no changes to routing logic.
"""

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from backend.models.enums import DraftStatus, Platform
from backend.models.schemas import DraftUpdate
from backend.repositories.draft_repository import DraftRepository
from backend.services.draft_service import DraftService
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.ingest_guideline import ingest_guideline_task
from backend.workers.tasks.publish_post import publish_post_task
from slack_app.utils.block_builder import (
    build_app_home,
    build_approval_modal,
    build_draft_card,
    build_generation_modal,
    build_manual_post_modal,
    build_schedule_modal,
    build_upload_modal,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Type alias for handler context bundles
# ---------------------------------------------------------------------------

BlockActionContext = dict[str, Any]
ViewSubmissionContext = dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slack_headers() -> dict[str, str]:
    token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    return {"Authorization": f"Bearer {token}"}


def _parse_draft_value(action_value: str) -> tuple[str, str]:
    """Split 'draft_id|platform' action value into its components."""
    parts = action_value.split("|")
    draft_id = parts[0]
    platform = parts[1] if len(parts) > 1 else "threads"
    return draft_id, platform


async def _open_modal(trigger_id: str, view: dict[str, Any]) -> None:
    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/views.open",
            headers=_slack_headers(),
            json={"trigger_id": trigger_id, "view": view},
        )
        if not res.json().get("ok"):
            logger.error("slack_modal_open_error", error=res.json())


# ---------------------------------------------------------------------------
# block_actions handlers
# ---------------------------------------------------------------------------


async def _handle_open_upload_modal(ctx: BlockActionContext) -> Response:
    await _open_modal(ctx["trigger_id"], build_upload_modal())
    return Response(status_code=200)


async def _handle_open_manual_post_modal(ctx: BlockActionContext) -> Response:
    await _open_modal(ctx["trigger_id"], build_manual_post_modal())
    return Response(status_code=200)


async def _handle_home_pagination(ctx: BlockActionContext) -> Response:
    action_value = ctx["action_value"]
    page_offset = int(action_value) if action_value.isdigit() else 0
    repo = DraftRepository(ctx["session"])
    drafts = await repo.get_recent_drafts(limit=10, offset=page_offset)
    home_view = build_app_home(drafts=drafts, offset=page_offset)

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/views.publish",
            headers=_slack_headers(),
            json={"user_id": ctx["user_id"], "view": home_view},
        )
        if not res.json().get("ok"):
            logger.error(
                "home_pagination_publish_error",
                error=res.json(),
                user_id=ctx["user_id"],
                page_offset=page_offset,
            )
    return Response(status_code=200)


async def _handle_open_generation_modal(ctx: BlockActionContext) -> Response:
    modal_view = build_generation_modal(channel_id=ctx["user_id"])
    await _open_modal(ctx["trigger_id"], modal_view)
    return Response(status_code=200)


async def _handle_open_draft_details(ctx: BlockActionContext) -> Response:
    draft_id, _ = _parse_draft_value(ctx["action_value"])
    if draft_id.isdigit():
        repo = DraftRepository(ctx["session"])
        db_draft = await repo.get_by_id(int(draft_id))
        if db_draft:
            modal_view = build_approval_modal(
                topic=db_draft.topic,
                draft=db_draft.content or "",
                platform=db_draft.platform,
                draft_id=str(db_draft.id),
                channel_id="",
                message_ts="",
            )
            await _open_modal(ctx["trigger_id"], modal_view)
    return Response(status_code=200)


async def _handle_schedule_draft(ctx: BlockActionContext) -> Response:
    draft_id, platform = _parse_draft_value(ctx["action_value"])
    if draft_id.isdigit():
        repo = DraftRepository(ctx["session"])
        db_draft = await repo.get_by_id(int(draft_id))
        if db_draft:
            sched_ts = (
                int(db_draft.scheduled_at.timestamp())
                if db_draft.scheduled_at
                else None
            )
            modal_view = build_schedule_modal(
                draft_id=draft_id,
                platform=platform,
                scheduled_at=sched_ts,
            )
            await _open_modal(ctx["trigger_id"], modal_view)
    return Response(status_code=200)


async def _handle_publish_draft(ctx: BlockActionContext) -> Response:
    draft_id, platform = _parse_draft_value(ctx["action_value"])
    draft_text = ctx["draft_text"]

    if draft_id.isdigit():
        repo = DraftRepository(ctx["session"])
        db_draft = await repo.get_by_id(int(draft_id))
        if db_draft:
            draft_text = db_draft.content or draft_text
        await repo.update(int(draft_id), DraftUpdate(status=DraftStatus.PUBLISHED))

    await publish_post_task.kiq(  # type: ignore[call-overload]
        post_id=draft_id, platform=platform, content=draft_text
    )
    async with httpx.AsyncClient() as client:
        await client.post(
            ctx["response_url"],
            json={"replace_original": True, "text": SLACK_UI["interact_approved_text"]},
        )
    return Response(status_code=200)


async def _handle_reject_draft(ctx: BlockActionContext) -> Response:
    draft_id, _ = _parse_draft_value(ctx["action_value"])
    if draft_id.isdigit():
        repo = DraftRepository(ctx["session"])
        await repo.update(int(draft_id), DraftUpdate(status=DraftStatus.REJECTED))

    async with httpx.AsyncClient() as client:
        await client.post(
            ctx["response_url"],
            json={"replace_original": True, "text": SLACK_UI["interact_rejected_text"]},
        )
    return Response(status_code=200)


async def _handle_edit_draft(ctx: BlockActionContext) -> Response:
    draft_id, platform = _parse_draft_value(ctx["action_value"])
    payload = ctx["payload"]
    message_ts = payload.get("message", {}).get("ts", "")
    msg_channel_id = payload.get("container", {}).get("channel_id", "")

    modal_view = build_approval_modal(
        topic=ctx["topic"],
        draft=ctx["draft_text"],
        platform=platform,
        draft_id=draft_id,
        channel_id=msg_channel_id,
        message_ts=message_ts,
    )
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://slack.com/api/views.open",
            headers=_slack_headers(),
            json={"trigger_id": ctx["trigger_id"], "view": modal_view},
        )
    return Response(status_code=200)


async def _handle_regenerate_draft(ctx: BlockActionContext) -> Response:
    draft_id, platform = _parse_draft_value(ctx["action_value"])
    payload = ctx["payload"]
    channel_id = str(payload.get("channel", {}).get("id", ""))

    await generate_draft_task.kiq(  # type: ignore[call-overload]
        topic=ctx["topic"],
        platform=platform,
        user_id=ctx["user_id"],
        channel_id=channel_id,
        draft_id=draft_id,
    )
    async with httpx.AsyncClient() as client:
        await client.post(
            ctx["response_url"],
            json={
                "replace_original": True,
                "text": SLACK_UI["interact_regenerate_text"],
            },
        )
    return Response(status_code=200)


# Dispatch table: action_id → handler
BLOCK_ACTION_HANDLERS: dict[
    str, Any  # Callable[[BlockActionContext], Awaitable[Response]]
] = {
    "action_open_upload_modal": _handle_open_upload_modal,
    "action_open_manual_post_modal": _handle_open_manual_post_modal,
    "action_home_drafts_prev": _handle_home_pagination,
    "action_home_drafts_next": _handle_home_pagination,
    "action_open_generation_modal": _handle_open_generation_modal,
    "action_open_draft_details": _handle_open_draft_details,
    "action_schedule_draft": _handle_schedule_draft,
    "action_publish_draft": _handle_publish_draft,
    "action_reject_draft": _handle_reject_draft,
    "action_edit_draft": _handle_edit_draft,
    "action_regenerate_draft": _handle_regenerate_draft,
}

# Actions that require response_url to be present
_MESSAGE_ACTIONS = {
    "action_publish_draft",
    "action_reject_draft",
    "action_edit_draft",
    "action_regenerate_draft",
}


def _extract_draft_text(payload: dict[str, Any]) -> str:
    """Pull draft text from message blocks (fallback when no DB record)."""
    blocks = payload.get("message", {}).get("blocks", [])
    for block in blocks:
        text = block.get("text", {}).get("text", "")
        if "```" in text:
            return text.replace("```", "").strip()
    return ""


async def _resolve_topic_and_draft(
    session: AsyncSession, draft_id: str, fallback_draft_text: str
) -> tuple[str, str]:
    """Load topic and content from DB if draft_id is numeric."""
    topic = "Медичний пост"
    draft_text = fallback_draft_text
    if draft_id.isdigit():
        repo = DraftRepository(session)
        db_draft = await repo.get_by_id(int(draft_id))
        if db_draft:
            topic = db_draft.topic
            draft_text = db_draft.content or draft_text
    return topic, draft_text


async def dispatch_block_action(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    """Route a block_actions payload to the correct handler via BLOCK_ACTION_HANDLERS."""
    user_id = str(payload.get("user", {}).get("id", ""))
    trigger_id = str(payload.get("trigger_id", ""))
    action = payload.get("actions", [])[0]
    action_id = action.get("action_id")
    action_value = action.get("value", "temp_id|threads")
    response_url = payload.get("response_url")

    logger.info("slack_block_action", action_id=action_id, trigger_id=trigger_id)

    handler = BLOCK_ACTION_HANDLERS.get(action_id)
    if handler is None:
        logger.warning("slack_unknown_action_id", action_id=action_id)
        return Response(status_code=200)

    if action_id in _MESSAGE_ACTIONS and not response_url:
        logger.warning(
            "slack_interaction_missing_url_for_message_action", action_id=action_id
        )
        return Response(status_code=200)

    draft_id, _ = _parse_draft_value(action_value)
    fallback_text = _extract_draft_text(payload)
    topic, draft_text = await _resolve_topic_and_draft(session, draft_id, fallback_text)

    ctx: BlockActionContext = {
        "payload": payload,
        "session": session,
        "user_id": user_id,
        "trigger_id": trigger_id,
        "action_id": action_id,
        "action_value": action_value,
        "response_url": response_url,
        "topic": topic,
        "draft_text": draft_text,
    }
    return await handler(ctx)


# ---------------------------------------------------------------------------
# view_submission handlers
# ---------------------------------------------------------------------------


async def _handle_generate_draft_modal(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    view = payload["view"]
    state_values = view.get("state", {}).get("values", {})
    user_id = str(payload.get("user", {}).get("id", ""))
    channel_id = view.get("private_metadata")

    topic = (
        state_values.get("block_topic_input", {})
        .get("input_topic", {})
        .get("value", "")
        .strip()
    )
    block_state = state_values.get("block_platform_select", {}).get(
        "input_platform_select", {}
    )
    selected_option = block_state.get("selected_option")
    platform = Platform(
        selected_option.get("value", "telegram") if selected_option else "telegram"
    )

    logger.info(
        "slack_generation_modal_submitted",
        user_id=user_id,
        topic=topic,
        platform=platform,
    )

    draft_service = DraftService(session)
    await draft_service.generate_draft_from_slack(
        user_id=user_id, topic=topic, platform=platform, channel_id=channel_id
    )

    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={
                "channel": channel_id,
                "text": SLACK_UI["cmd_accepted"].format(topic=topic, platform=platform),
            },
        )

    return Response(
        content=json.dumps({"response_action": "clear"}),
        media_type="application/json",
        status_code=200,
    )


async def _handle_edit_draft_modal(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    view = payload["view"]
    state_values = view.get("state", {}).get("values", {})
    user_id = str(payload.get("user", {}).get("id", ""))

    draft_content = (
        state_values.get("block_draft_content", {})
        .get("input_draft_content", {})
        .get("value", "")
    )

    block_state = state_values.get("block_platform_select", {}).get(
        "input_platform_select", {}
    )
    selected_option = block_state.get("selected_option")
    platform_raw = (
        selected_option.get("value", "telegram") if selected_option else "telegram"
    )
    platform = Platform(platform_raw) if platform_raw else None

    metadata_parts = view.get("private_metadata", "").split("|")
    topic = metadata_parts[0] if len(metadata_parts) > 0 else "Медичний пост"
    draft_id = metadata_parts[1] if len(metadata_parts) > 1 else "temp_id"
    msg_channel_id = metadata_parts[2] if len(metadata_parts) > 2 else ""
    message_ts = metadata_parts[3] if len(metadata_parts) > 3 else ""

    logger.info(
        "slack_edit_modal_submitted",
        user_id=user_id,
        platform=platform,
        draft_id=draft_id,
    )

    if draft_id.isdigit():
        repo = DraftRepository(session)
        await repo.update(
            int(draft_id), DraftUpdate(content=draft_content, platform=platform)
        )

    if msg_channel_id and message_ts:
        updated_blocks = build_draft_card(
            topic=topic,
            draft=draft_content,
            user_id=user_id,
            draft_id=draft_id,
            platform=platform.value if platform else "threads",
        )
        slack_token = (
            settings.SLACK_BOT_TOKEN.get_secret_value()
            if settings.SLACK_BOT_TOKEN
            else ""
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/chat.update",
                headers={"Authorization": f"Bearer {slack_token}"},
                json={
                    "channel": msg_channel_id,
                    "ts": message_ts,
                    "text": SLACK_UI["draft_ready_fallback"].format(topic=topic),
                    "blocks": updated_blocks,
                },
            )

    return Response(
        content=json.dumps({"response_action": "clear"}),
        media_type="application/json",
        status_code=200,
    )


async def _handle_manual_post_modal(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    view = payload["view"]
    state_values = view.get("state", {}).get("values", {})
    user_id = str(payload.get("user", {}).get("id", ""))

    content = (
        state_values.get("block_manual_content", {})
        .get("input_manual_content", {})
        .get("value", "")
        .strip()
    )

    block_state = state_values.get("block_platform_select", {}).get(
        "input_platform_select", {}
    )
    selected_option = block_state.get("selected_option")
    platform_raw = (
        selected_option.get("value", "telegram") if selected_option else "telegram"
    )
    platform = Platform(platform_raw)

    schedule_timestamp = (
        state_values.get("block_schedule_time", {})
        .get("input_schedule_time", {})
        .get("selected_date_time")
    )
    scheduled_at = (
        datetime.fromtimestamp(int(schedule_timestamp), tz=timezone.utc)
        if schedule_timestamp
        else None
    )

    draft_service = DraftService(session)
    await draft_service.process_manual_post(
        user_id=user_id,
        content=content,
        platform=platform,
        scheduled_at=scheduled_at,
    )

    logger.info(
        "manual_post_processed",
        user_id=user_id,
        platform=platform,
        scheduled=bool(scheduled_at),
    )

    return Response(
        content=json.dumps({"response_action": "clear"}),
        media_type="application/json",
        status_code=200,
    )


async def _handle_schedule_draft_modal(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    view = payload["view"]
    state_values = view.get("state", {}).get("values", {})

    metadata_parts = view.get("private_metadata", "").split("|")
    draft_id = metadata_parts[0] if len(metadata_parts) > 0 else ""
    platform = metadata_parts[1] if len(metadata_parts) > 1 else "threads"

    schedule_timestamp = (
        state_values.get("block_schedule_time", {})
        .get("input_schedule_time", {})
        .get("selected_date_time")
    )

    if not schedule_timestamp or not draft_id.isdigit():
        return Response(
            content=json.dumps(
                {
                    "response_action": "errors",
                    "errors": {
                        "block_schedule_time": SLACK_UI["schedule_no_time_error"]
                    },
                }
            ),
            media_type="application/json",
            status_code=200,
        )

    scheduled_at = datetime.fromtimestamp(int(schedule_timestamp), tz=timezone.utc)
    repo = DraftRepository(session)
    await repo.update(
        int(draft_id),
        DraftUpdate(status=DraftStatus.SCHEDULED, scheduled_at=scheduled_at),
    )

    logger.info(
        "draft_scheduled",
        draft_id=draft_id,
        platform=platform,
        scheduled_at=scheduled_at.isoformat(),
    )

    return Response(
        content=json.dumps({"response_action": "clear"}),
        media_type="application/json",
        status_code=200,
    )


async def _handle_upload_guideline_modal(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    view = payload["view"]
    state_values = view.get("state", {}).get("values", {})
    user_id = str(payload.get("user", {}).get("id", ""))

    files = (
        state_values.get("block_file_upload", {}).get("input_file", {}).get("files", [])
    )
    if not files:
        return Response(status_code=400)

    file_info = files[0]
    file_url = file_info.get("url_private_download")
    file_name = file_info.get("name")

    logger.info("slack_file_uploaded", user_id=user_id, file_name=file_name)

    await ingest_guideline_task.kiq(  # type: ignore[call-overload]
        file_url=file_url, file_name=file_name, user_id=user_id
    )

    return Response(
        content=json.dumps({"response_action": "clear"}),
        media_type="application/json",
        status_code=200,
    )


# Dispatch table: callback_id → handler
VIEW_HANDLERS: dict[
    str, Any  # Callable[[dict, AsyncSession], Awaitable[Response]]
] = {
    "modal_generate_draft": _handle_generate_draft_modal,
    "modal_edit_draft": _handle_edit_draft_modal,
    "modal_manual_post": _handle_manual_post_modal,
    "modal_schedule_draft": _handle_schedule_draft_modal,
    "modal_upload_guideline": _handle_upload_guideline_modal,
}


async def dispatch_view_submission(
    payload: dict[str, Any], session: AsyncSession
) -> Response:
    """Route a view_submission payload to the correct handler via VIEW_HANDLERS."""
    view = payload.get("view", {})
    callback_id = view.get("callback_id")

    handler = VIEW_HANDLERS.get(callback_id)
    if handler is None:
        logger.warning("slack_unknown_callback_id", callback_id=callback_id)
        return Response(status_code=200)

    return await handler(payload, session)
