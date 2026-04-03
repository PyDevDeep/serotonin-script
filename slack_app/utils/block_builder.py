from typing import Any

from backend.config.lexicon import SLACK_UI


def build_draft_card(topic: str, draft: str, user_id: str) -> list[dict[str, Any]]:
    """Генерує картку чернетки з кнопками дій."""
    return [
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
                    "value": "publish",
                    "action_id": "action_publish_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_edit"],
                        "emoji": True,
                    },
                    "value": "edit",
                    "action_id": "action_edit_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_regenerate"],
                        "emoji": True,
                    },
                    "value": "regenerate",
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
                    "value": "reject",
                    "action_id": "action_reject_draft",
                },
            ],
        },
    ]


def build_approval_modal(topic: str, draft: str, platform: str = "telegram") -> dict[str, Any]:
    """Генерує модальне вікно для редагування тексту перед публікацією."""
    return {
        "type": "modal",
        "callback_id": "modal_edit_draft",
        "private_metadata": topic,  # Зберігаємо тему для контексту
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
