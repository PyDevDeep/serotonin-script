import json
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from backend.models.db_models import User
from backend.models.enums import DraftStatus, Platform
from backend.models.schemas import DraftCreate, DraftUpdate
from backend.repositories.draft_repository import DraftRepository
from backend.workers.dependencies import get_db_session
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
router = APIRouter(prefix="/slack", tags=["Slack Integration"])


@router.post("/commands")
async def slack_slash_command(request: Request):
    form_data = await request.form()
    command = form_data.get("command")
    trigger_id = form_data.get("trigger_id")
    channel_id = str(form_data.get("channel_id"))

    if command != "/draft":
        return {"response_type": "ephemeral", "text": SLACK_UI["cmd_unknown"]}

    # Відкриваємо модалку замість парсингу тексту
    modal_view = build_generation_modal(channel_id=channel_id)
    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    headers = {"Authorization": f"Bearer {slack_token}"}

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://slack.com/api/views.open",
            headers=headers,
            json={"trigger_id": trigger_id, "view": modal_view},
        )
        if not res.json().get("ok"):
            logger.error("slack_modal_open_error", error=res.json())

    # Повертаємо 200 OK без тіла, щоб Slack не дублював повідомлення
    return Response(status_code=200)


@router.post("/interactions")
async def slack_interactions(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    form_data = await request.form()
    payload_str = form_data.get("payload")

    if not payload_str:
        raise HTTPException(status_code=400, detail="Missing payload")

    payload = json.loads(str(payload_str))
    user_id = str(payload.get("user", {}).get("id", ""))
    interaction_type = payload.get("type")

    slack_token = (
        settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else ""
    )
    headers = {"Authorization": f"Bearer {slack_token}"}

    if interaction_type == "block_actions":
        trigger_id = str(payload.get("trigger_id", ""))
        action = payload.get("actions", [])[0]
        action_id = action.get("action_id")
        response_url = payload.get("response_url")
        logger.info("slack_block_action", action_id=action_id, trigger_id=trigger_id)
        action_value = action.get("value", "temp_id|telegram")
        value_parts = action_value.split("|")
        draft_id = value_parts[0]
        platform = value_parts[1] if len(value_parts) > 1 else "telegram"
        # --- ГРУПА 1: Дії, що відкривають модалки (response_url НЕ потрібен) ---
        if action_id == "action_open_upload_modal":
            modal_view = build_upload_modal()
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://slack.com/api/views.open",
                    headers=headers,
                    json={"trigger_id": trigger_id, "view": modal_view},
                )
            return Response(status_code=200)

        if action_id == "action_open_manual_post_modal":
            modal_view = build_manual_post_modal()
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://slack.com/api/views.open",
                    headers=headers,
                    json={"trigger_id": trigger_id, "view": modal_view},
                )
                if not res.json().get("ok"):
                    logger.error("manual_post_modal_open_error", error=res.json())
            return Response(status_code=200)

        if action_id in ("action_home_drafts_prev", "action_home_drafts_next"):
            page_offset = int(action_value) if action_value.isdigit() else 0
            repo = DraftRepository(session)
            drafts = await repo.get_recent_drafts(limit=10, offset=page_offset)
            home_view = build_app_home(drafts=drafts, offset=page_offset)
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://slack.com/api/views.publish",
                    headers=headers,
                    json={"user_id": user_id, "view": home_view},
                )
                if not res.json().get("ok"):
                    logger.error(
                        "home_pagination_publish_error",
                        error=res.json(),
                        user_id=user_id,
                        page_offset=page_offset,
                    )
            return Response(status_code=200)

        if action_id == "action_open_generation_modal":
            modal_view = build_generation_modal(channel_id=user_id)
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://slack.com/api/views.open",
                    headers=headers,
                    json={"trigger_id": trigger_id, "view": modal_view},
                )
            return Response(status_code=200)
        if action_id == "action_open_draft_details":
            if draft_id.isdigit():
                repo = DraftRepository(session)
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
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            "https://slack.com/api/views.open",
                            headers=headers,
                            json={"trigger_id": trigger_id, "view": modal_view},
                        )
            return Response(status_code=200)

        if action_id == "action_schedule_draft":
            if draft_id.isdigit():
                repo = DraftRepository(session)
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
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            "https://slack.com/api/views.open",
                            headers=headers,
                            json={"trigger_id": trigger_id, "view": modal_view},
                        )
            return Response(status_code=200)
        # --- ГРУПА 2: Дії з повідомленнями (response_url ОБОВ'ЯЗКОВИЙ) ---
        if action_id in [
            "action_publish_draft",
            "action_reject_draft",
            "action_edit_draft",
            "action_regenerate_draft",
        ]:
            if not response_url:
                logger.warning(
                    "slack_interaction_missing_url_for_message_action",
                    action_id=action_id,
                )
                return Response(status_code=200)

            # Логіка парсингу тексту повідомлення
            blocks = payload.get("message", {}).get("blocks", [])
            raw_draft = blocks[1]["text"]["text"] if len(blocks) > 1 else ""
            draft_text = raw_draft.replace("```", "").strip()
            topic = "Медичний пост"

            async with httpx.AsyncClient() as client:
                if action_id == "action_publish_draft":
                    # ДОДАНО: Змінюємо статус на Опубліковано
                    if draft_id.isdigit():
                        repo = DraftRepository(session)
                        await repo.update(
                            int(draft_id), DraftUpdate(status=DraftStatus.PUBLISHED)
                        )

                    await publish_post_task.kiq(
                        post_id=draft_id, platform=platform, content=draft_text
                    )
                    await client.post(
                        response_url,
                        json={
                            "replace_original": True,
                            "text": SLACK_UI["interact_approved_text"],
                        },
                    )

                elif action_id == "action_reject_draft":
                    await client.post(
                        response_url,
                        json={
                            "replace_original": True,
                            "text": SLACK_UI["interact_rejected_text"],
                        },
                    )

                elif action_id == "action_edit_draft":
                    message_ts = payload.get("message", {}).get("ts", "")
                    msg_channel_id = payload.get("container", {}).get("channel_id", "")

                    modal_view = build_approval_modal(
                        topic=topic,
                        draft=draft_text,
                        platform=platform,
                        draft_id=draft_id,
                        channel_id=msg_channel_id,
                        message_ts=message_ts,
                    )
                    await client.post(
                        "https://slack.com/api/views.open",
                        headers=headers,
                        json={"trigger_id": trigger_id, "view": modal_view},
                    )

                elif action_id == "action_regenerate_draft":
                    channel_id = str(payload.get("channel", {}).get("id", ""))
                    await generate_draft_task.kiq(  # type: ignore[call-overload]
                        topic=topic,
                        platform=platform,
                        user_id=user_id,
                        channel_id=channel_id,
                        draft_id=draft_id,
                    )
                    await client.post(
                        response_url,
                        json={
                            "replace_original": True,
                            "text": SLACK_UI["interact_regenerate_text"],
                        },
                    )

        return Response(status_code=200)

    elif interaction_type == "view_submission":
        view = payload.get("view", {})
        callback_id = view.get("callback_id")
        state_values = view.get("state", {}).get("values", {})

        # --- СЦЕНАРІЙ 1: Генерація нового драфту ---
        if callback_id == "modal_generate_draft":
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
                selected_option.get("value", "telegram")
                if selected_option
                else "telegram"
            )

            logger.info(
                "slack_generation_modal_submitted",
                user_id=user_id,
                topic=topic,
                platform=platform,
            )

            # --- ДОДАНО: СТВОРЕННЯ КОРИСТУВАЧА ТА ДРАФТУ В БД ---
            # 1. Знаходимо або створюємо користувача (Slack ID)
            user_query = await session.execute(
                select(User).where(User.username == user_id)
            )
            db_user = user_query.scalar_one_or_none()
            if not db_user:
                db_user = User(username=user_id)
                session.add(db_user)
                await session.flush()

            # 2. Створюємо драфт (статус pending)
            repo = DraftRepository(session)
            new_draft = await repo.create(
                DraftCreate(topic=topic, platform=platform, user_id=db_user.id)
            )
            real_draft_id = str(new_draft.id)
            # ---------------------------------------------------

            # Передаємо РЕАЛЬНИЙ ID з бази замість UUID
            await generate_draft_task.kiq(  # type: ignore[call-overload]
                topic=topic,
                platform=platform.value,
                user_id=user_id,
                channel_id=channel_id,
                draft_id=real_draft_id,
            )

            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers=headers,
                    json={
                        "channel": channel_id,
                        "text": SLACK_UI["cmd_accepted"].format(
                            topic=topic, platform=platform
                        ),
                    },
                )

            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )

        # --- СЦЕНАРІЙ 2: Збереження відредагованого драфту ---
        elif callback_id == "modal_edit_draft":
            draft_content = (
                state_values.get("block_draft_content", {})
                .get("input_draft_content", {})
                .get("value", "")
            )

            # Надійний парсинг селектора платформи
            block_state = state_values.get("block_platform_select", {}).get(
                "input_platform_select", {}
            )
            selected_option = block_state.get("selected_option")
            platform_raw = (
                selected_option.get("value", "telegram")
                if selected_option
                else "telegram"
            )
            platform = Platform(platform_raw) if platform_raw else None

            # 1. СПОЧАТКУ витягуємо метадані (ID, канали, топік)
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

            # 2. ПОТІМ зберігаємо в базу даних
            if draft_id.isdigit():
                repo = DraftRepository(session)
                await repo.update(
                    int(draft_id), DraftUpdate(content=draft_content, platform=platform)
                )

            # 3. ПОТІМ перемальовуємо повідомлення новою карткою з кнопками
            if msg_channel_id and message_ts:
                updated_blocks = build_draft_card(
                    topic=topic,
                    draft=draft_content,
                    user_id=user_id,
                    draft_id=draft_id,
                    platform=platform.value if platform else "telegram",
                )
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://slack.com/api/chat.update",
                        headers=headers,
                        json={
                            "channel": msg_channel_id,
                            "ts": message_ts,
                            "text": SLACK_UI["draft_ready_fallback"].format(
                                topic=topic
                            ),
                            "blocks": updated_blocks,
                        },
                    )

            # 4. В КІНЦІ закриваємо модалку одним return
            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )

        # --- СЦЕНАРІЙ 3: Ручний пост ---
        elif callback_id == "modal_manual_post":
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
                selected_option.get("value", "telegram")
                if selected_option
                else "telegram"
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

            # Знаходимо або створюємо користувача
            user_query = await session.execute(
                select(User).where(User.username == user_id)
            )
            db_user = user_query.scalar_one_or_none()
            if not db_user:
                db_user = User(username=user_id)
                session.add(db_user)
                await session.flush()

            repo = DraftRepository(session)

            if scheduled_at:
                new_draft = await repo.create(
                    DraftCreate(
                        topic=content[:80], platform=platform, user_id=db_user.id
                    )
                )
                await repo.update(
                    new_draft.id,
                    DraftUpdate(
                        content=content,
                        status=DraftStatus.SCHEDULED,
                        scheduled_at=scheduled_at,
                    ),
                )
                logger.info(
                    "manual_post_scheduled",
                    user_id=user_id,
                    platform=platform,
                    scheduled_at=scheduled_at.isoformat(),
                )
            else:
                new_draft = await repo.create(
                    DraftCreate(
                        topic=content[:80], platform=platform, user_id=db_user.id
                    )
                )
                await repo.update(
                    new_draft.id,
                    DraftUpdate(content=content, status=DraftStatus.PUBLISHED),
                )
                await publish_post_task.kiq(
                    post_id=str(new_draft.id), platform=platform.value, content=content
                )
                logger.info("manual_post_published", user_id=user_id, platform=platform)

            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )

        # --- СЦЕНАРІЙ 4: Планування публікації ---
        elif callback_id == "modal_schedule_draft":
            metadata_parts = view.get("private_metadata", "").split("|")
            draft_id = metadata_parts[0] if len(metadata_parts) > 0 else ""
            platform = metadata_parts[1] if len(metadata_parts) > 1 else "telegram"

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
                                "block_schedule_time": SLACK_UI[
                                    "schedule_no_time_error"
                                ]
                            },
                        }
                    ),
                    media_type="application/json",
                    status_code=200,
                )

            scheduled_at = datetime.fromtimestamp(
                int(schedule_timestamp), tz=timezone.utc
            )
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

        # --- СЦЕНАРІЙ 5: Завантаження гайдлайну ---
        elif callback_id == "modal_upload_guideline":
            files = (
                state_values.get("block_file_upload", {})
                .get("input_file", {})
                .get("files", [])
            )
            if not files:
                return Response(status_code=400)

            file_info = files[0]
            file_url = file_info.get("url_private_download")
            file_name = file_info.get("name")

            logger.info("slack_file_uploaded", user_id=user_id, file_name=file_name)

            await ingest_guideline_task.kiq(
                file_url=file_url, file_name=file_name, user_id=user_id
            )

            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )

    return Response(status_code=200)


@router.post("/events")
async def slack_events(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    """Обробка Events API (наприклад, відкриття вкладки Home)."""
    data = await request.json()

    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}

    event = data.get("event", {})
    user_id = event.get("user")

    logger.info("slack_event_received", event_type=event.get("type"), user_id=user_id)

    if event.get("type") == "app_home_opened":
        # 1. Витягуємо останні 10 драфтів
        repo = DraftRepository(session)
        recent_drafts = await repo.get_recent_drafts(limit=10)

        logger.info(
            "slack_home_opened", user_id=user_id, drafts_count=len(recent_drafts)
        )

        # 2. Рендеримо дашборд
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

    return Response(status_code=200)
