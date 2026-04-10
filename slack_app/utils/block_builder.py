from typing import Any

from backend.config.lexicon import SLACK_UI
from backend.models.db_models import Draft


def build_draft_card(
    topic: str,
    draft: str,
    user_id: str,
    draft_id: str,
    platform: str,
    is_valid: bool = True,
) -> list[dict[str, Any]]:
    """Генерує картку чернетки з кнопками дій. Якщо is_valid=False, додає попередження."""

    topic_short = topic[:100] if len(topic) > 100 else topic
    header_text = f"{SLACK_UI['draft_ready_header'].format(topic=topic_short)} | 📢 {platform.upper()}"
    if not is_valid:
        header_text = SLACK_UI["validation_failed_header"].format(
            platform=platform.upper()
        )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True,
            },
        }
    ]

    if not is_valid:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": SLACK_UI["validation_failed_warning"],
                },
            }
        )

    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```{draft}```"}}
    )

    fact_check_status = (
        SLACK_UI["fact_check_ok"] if is_valid else SLACK_UI["fact_check_failed"]
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": SLACK_UI["ordered_by"].format(user_id=user_id),
                },
                {
                    "type": "mrkdwn",
                    "text": f"{fact_check_status} | {SLACK_UI['fact_check_sources']}",
                },
            ],
        }
    )

    # Action buttons block appended at the end
    blocks.append(
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
                    "value": f"{draft_id}|{platform}",
                    "action_id": "action_publish_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["btn_schedule"],
                        "emoji": True,
                    },
                    "value": f"{draft_id}|{platform}",
                    "action_id": "action_schedule_draft",
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
        }
    )

    return blocks


def build_approval_modal(
    topic: str,
    draft: str,
    platform: str = "threads",
    draft_id: str = "unknown",
    channel_id: str = "",
    message_ts: str = "",
) -> dict[str, Any]:
    """Генерує модальне вікно для редагування тексту перед публікацією."""
    return {
        "type": "modal",
        "callback_id": "modal_edit_draft",
        "private_metadata": f"{topic}|{draft_id}|{channel_id}|{message_ts}",
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


def build_schedule_modal(
    draft_id: str, platform: str, scheduled_at: int | None = None
) -> dict[str, Any]:
    """Генерує мінімальну модалку для вибору часу планування публікації."""
    element: dict[str, Any] = {
        "type": "datetimepicker",
        "action_id": "input_schedule_time",
    }
    if scheduled_at is not None:
        element["initial_date_time"] = scheduled_at

    return {
        "type": "modal",
        "callback_id": "modal_schedule_draft",
        "private_metadata": f"{draft_id}|{platform}",
        "title": {
            "type": "plain_text",
            "text": SLACK_UI["schedule_modal_title"],
            "emoji": True,
        },
        "submit": {
            "type": "plain_text",
            "text": SLACK_UI["schedule_modal_submit"],
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
                "block_id": "block_schedule_time",
                "element": element,
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["schedule_modal_label"],
                    "emoji": True,
                },
            }
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
            {
                "type": "input",
                "block_id": "block_source_url",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "input_source_url",
                    "multiline": False,
                    "placeholder": {
                        "type": "plain_text",
                        "text": SLACK_UI["gen_modal_url_placeholder"],
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["gen_modal_url_label"],
                    "emoji": True,
                },
            },
        ],
    }


def build_manual_post_modal() -> dict[str, Any]:
    """Генерує модалку для ручного написання і публікації/планування поста."""
    return {
        "type": "modal",
        "callback_id": "modal_manual_post",
        "title": {
            "type": "plain_text",
            "text": SLACK_UI["manual_post_modal_title"],
            "emoji": True,
        },
        "submit": {
            "type": "plain_text",
            "text": SLACK_UI["manual_post_modal_submit"],
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
                "block_id": "block_manual_content",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "input_manual_content",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Enter your post text...",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["manual_post_modal_content_label"],
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
                    "text": SLACK_UI["manual_post_modal_platform_label"],
                    "emoji": True,
                },
            },
            {
                "type": "input",
                "block_id": "block_schedule_time",
                "optional": True,
                "element": {
                    "type": "datetimepicker",
                    "action_id": "input_schedule_time",
                },
                "label": {
                    "type": "plain_text",
                    "text": SLACK_UI["manual_post_modal_schedule_label"],
                    "emoji": True,
                },
            },
        ],
    }


def build_app_home(
    drafts: list[Draft] | None = None, offset: int = 0, page_size: int = 10
) -> dict[str, Any]:
    """Build the App Home view with a dashboard of recent drafts and pagination controls."""
    if drafts is None:
        drafts = []

    blocks: list[dict[str, Any]] = [
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
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": SLACK_UI["home_btn_manual_post"],
                        "emoji": True,
                    },
                    "action_id": "action_open_manual_post_modal",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": SLACK_UI["home_drafts_header"],
                "emoji": True,
            },
        },
    ]

    if not drafts:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": SLACK_UI["home_drafts_empty"]},
            }
        )
    else:
        for d in drafts:
            status_emoji = SLACK_UI.get(
                f"status_emoji_{d.status}", SLACK_UI["status_emoji_pending"]
            )

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": SLACK_UI["home_draft_card_text"].format(
                            topic=d.topic,
                            platform=d.platform.upper(),
                            status_emoji=status_emoji,
                            status=d.status,
                        ),
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": SLACK_UI["home_draft_open_btn"],
                                "emoji": True,
                            },
                            "value": f"{d.id}|{d.platform}",
                            "action_id": "action_open_draft_details",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": SLACK_UI["home_draft_delete_btn"],
                                "emoji": True,
                            },
                            "style": "danger",
                            "value": str(d.id),
                            "action_id": "action_delete_draft",
                        },
                    ],
                }
            )

    pagination_elements: list[dict[str, Any]] = []
    if offset > 0:
        pagination_elements.append(
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": SLACK_UI["home_btn_prev_page"],
                    "emoji": True,
                },
                "value": str(offset - page_size),
                "action_id": "action_home_drafts_prev",
            }
        )
    if len(drafts) == page_size:
        pagination_elements.append(
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": SLACK_UI["home_btn_next_page"],
                    "emoji": True,
                },
                "value": str(offset + page_size),
                "action_id": "action_home_drafts_next",
            }
        )
    if pagination_elements:
        blocks.append({"type": "actions", "elements": pagination_elements})

    return {"type": "home", "blocks": blocks}


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
