from typing import Any

from backend.config.lexicon import SLACK_UI


def build_draft_card(
    topic: str, draft: str, user_id: str, draft_id: str, platform: str
) -> list[dict[str, Any]]:
    """Генерує картку чернетки з кнопками дій."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{SLACK_UI['draft_ready_header'].format(topic=topic)} | 📢 {platform.upper()}",
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
                },
                {
                    "type": "mrkdwn",
                    "text": f"{SLACK_UI['fact_check_ok']} | {SLACK_UI['fact_check_sources']}",
                },
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
                    "value": f"{draft_id}|{platform}",  # ПРОШИВАЄМО ID ТА ПЛАТФОРМУ
                    "action_id": "action_publish_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_edit"],
                        "emoji": True,
                    },
                    "value": f"{draft_id}|{platform}",
                    "action_id": "action_edit_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_regenerate"],
                        "emoji": True,
                    },
                    "value": f"{draft_id}|{platform}",
                    "action_id": "action_regenerate_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_reject"],
                        "emoji": True,
                    },
                    "style": "danger",
                    "value": f"{draft_id}|{platform}",
                    "action_id": "action_reject_draft",
                },
            ],
        },
    ]


def build_approval_modal(
    topic: str,
    draft: str,
    platform: str = "telegram",
    draft_id: str = "unknown",
    channel_id: str = "",
    message_ts: str = "",
) -> dict[str, Any]:
    """Генерує модальне вікно для редагування тексту перед публікацією."""
    return {
        "type": "modal",
        "callback_id": "modal_edit_draft",
        "private_metadata": f"{topic}|{draft_id}|{channel_id}|{message_ts}",  # ПРОШИВАЄМО 4 ПАРАМЕТРИ
        "title": {"type": "plain_text", "text": SLACK_UI["modal_title"], "emoji": True},
        "submit": {
            "type": "plain_text",
            "text": SLACK_UI["modal_submit"],
            "emoji": True,
        },
        "close": {
            "type": "plain_text",
            "text": SLACK_UI["modal_cancel"],
            "emoji": True,
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "block_draft_content",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "input_draft_content",
                    "multiline": True,
                    "initial_value": draft,
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["modal_input_label"],
                    "emoji": True,
                },
            },
            {
                "type": "input",
                "block_id": "block_platform_select",
                "element": {
                    "type": "static_select",
                    "action_id": "input_platform_select",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": platform.capitalize()},
                        "value": platform.lower(),
                    },
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Telegram"},
                            "value": "telegram",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Twitter"},
                            "value": "twitter",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Threads"},
                            "value": "threads",
                        },
                    ],
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["modal_platform_label"],
                    "emoji": True,
                },
            },
        ],
    }


def build_generation_modal(channel_id: str) -> dict[str, Any]:
    """Генерує стартове модальне вікно для вводу теми та платформи."""
    return {
        "type": "modal",
        "callback_id": "modal_generate_draft",
        "private_metadata": channel_id,
        "title": {
            "type": "plain_text",
            "text": SLACK_UI["gen_modal_title"],
            "emoji": True,
        },
        "submit": {
            "type": "plain_text",
            "text": SLACK_UI["gen_modal_submit"],
            "emoji": True,
        },
        "close": {
            "type": "plain_text",
            "text": SLACK_UI["modal_cancel"],
            "emoji": True,
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "block_topic_input",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "input_topic",
                    "multiline": False,
                    "placeholder": {
                        "type": "plain_text",
                        "text": SLACK_UI["gen_modal_topic_placeholder"],
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["gen_modal_topic_label"],
                    "emoji": True,
                },
            },
            {
                "type": "input",
                "block_id": "block_platform_select",
                "element": {
                    "type": "static_select",
                    "action_id": "input_platform_select",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "Telegram"},
                        "value": "telegram",
                    },
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Telegram"},
                            "value": "telegram",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Twitter"},
                            "value": "twitter",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Threads"},
                            "value": "threads",
                        },
                    ],
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["gen_modal_platform_label"],
                    "emoji": True,
                },
            },
        ],
    }


def build_app_home() -> dict[str, Any]:
    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": SLACK_UI["home_welcome"],
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": SLACK_UI["home_description"]},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": SLACK_UI["home_btn_create"],
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "action_open_generation_modal",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": SLACK_UI["home_btn_upload"],
                            "emoji": True,
                        },
                        "action_id": "action_open_upload_modal",
                    },
                ],
            },
        ],
    }


def build_upload_modal() -> dict[str, Any]:
    """Генерує модальне вікно для завантаження файлу в базу знань."""
    return {
        "type": "modal",
        "callback_id": "modal_upload_guideline",
        "title": {
            "type": "plain_text",
            "text": SLACK_UI["upload_modal_title"],
            "emoji": True,
        },
        "submit": {
            "type": "plain_text",
            "text": SLACK_UI["upload_modal_submit"],
            "emoji": True,
        },
        "close": {
            "type": "plain_text",
            "text": SLACK_UI["modal_cancel"],
            "emoji": True,
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "block_file_upload",
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["upload_modal_input_label"],
                },
                "element": {
                    "type": "file_input",
                    "action_id": "input_file",
                    "filetypes": ["pdf", "txt"],  # Обмежуємо формати
                    "max_files": 1,
                },
            }
        ],
    }
