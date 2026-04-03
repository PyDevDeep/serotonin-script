import json

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from backend.config.lexicon import SLACK_UI
from backend.config.settings import settings
from backend.workers.tasks.generate_draft import generate_draft_task
from backend.workers.tasks.publish_post import publish_post_task
from slack_app.utils.block_builder import (
    build_app_home,
    build_approval_modal,
    build_generation_modal,
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
async def slack_interactions(request: Request):
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

        if action_id == "action_open_generation_modal":
            modal_view = build_generation_modal(channel_id=user_id)
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
                    await publish_post_task.kiq(
                        post_id="temp_id", platform="telegram", content=draft_text
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
                    modal_view = build_approval_modal(
                        topic=topic, draft=draft_text, platform="telegram"
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
                        platform="telegram",
                        user_id=user_id,
                        channel_id=channel_id,
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
            channel_id = view.get("private_metadata")  # Дістаємо збережений канал
            topic = (
                state_values.get("block_topic_input", {})
                .get("input_topic", {})
                .get("value", "")
                .strip()
            )
            platform = (
                state_values.get("block_platform_select", {})
                .get("input_platform_select", {})
                .get("selected_option", {})
                .get("value", "telegram")
            )

            logger.info(
                "slack_generation_modal_submitted",
                user_id=user_id,
                topic=topic,
                platform=platform,
            )

            # Запускаємо генерацію
            await generate_draft_task.kiq(  # type: ignore[call-overload]
                topic=topic, platform=platform, user_id=user_id, channel_id=channel_id
            )

            # Відправляємо підтвердження в канал
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
            platform = (
                state_values.get("block_platform_select", {})
                .get("input_platform_select", {})
                .get("selected_option", {})
                .get("value", "telegram")
            )

            logger.info(
                "slack_edit_modal_submitted", user_id=user_id, platform=platform
            )
            await publish_post_task.kiq(
                post_id="temp_id", platform=platform, content=draft_content
            )

            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )
        # --- СЦЕНАРІЙ 3: Завантаження гайдлайну ---
        elif callback_id == "modal_upload_guideline":
            # Slack повертає масив об'єктів файлів
            files = (
                state_values.get("block_file_upload", {})
                .get("input_file", {})
                .get("files", [])
            )
            if not files:
                return Response(status_code=400)

            file_info = files[0]
            # file_url = file_info.get("url_private_download")
            file_name = file_info.get("name")

            logger.info("slack_file_uploaded", user_id=user_id, file_name=file_name)

            # TODO: Тут ми створимо таск `ingest_document_task`, який буде
            # скачувати файл за file_url (використовуючи Slack Token),
            # парсити PDF/TXT та векторизувати його у Qdrant.
            # await ingest_document_task.kiq(file_url=file_url, file_name=file_name)

            # Закриваємо модалку
            return Response(
                content=json.dumps({"response_action": "clear"}),
                media_type="application/json",
                status_code=200,
            )
    return Response(status_code=200)


@router.post("/events")
async def slack_events(request: Request):
    """Обробка Events API (наприклад, відкриття вкладки Home)."""
    data = await request.json()

    # 1. Підтвердження URL для Slack (виконується один раз при налаштуванні)
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}

    event = data.get("event", {})
    user_id = event.get("user")

    # 2. Коли користувач відкриває вкладку Home — малюємо йому дашборд
    if event.get("type") == "app_home_opened":
        slack_token = (
            settings.SLACK_BOT_TOKEN.get_secret_value()
            if settings.SLACK_BOT_TOKEN
            else ""
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/views.publish",
                headers={"Authorization": f"Bearer {slack_token}"},
                json={"user_id": user_id, "view": build_app_home()},
            )

    return Response(status_code=200)
