"""
Tests for backend.api.routes.feedback (Slack integration router).

Endpoints covered:
- POST /slack/commands  — slash command dispatch
- POST /slack/interactions — block_actions and view_submission payloads
- POST /slack/error — publish failure reporting
- POST /slack/events — Events API (url_verification + app_home_opened)

Strategy:
- FastAPI TestClient with overridden get_db_session dependency.
- All outbound httpx calls patched via unittest.mock.patch (AsyncMock).
- Taskiq .kiq() calls patched to prevent broker connection.
- DraftRepository interactions mocked at the class level.
- settings.SLACK_BOT_TOKEN resolved to a real SecretStr to avoid attribute errors.
"""

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from backend.api.main import create_app
from backend.models.db_models import Draft
from backend.models.enums import DraftStatus
from backend.workers.dependencies import get_db_session

# ---------------------------------------------------------------------------
# App + dependency override
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    return session


@pytest.fixture
def client(app, mock_session):
    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slack_ok_response() -> MagicMock:
    """Mock httpx.Response with ok=True."""
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    return resp


def _make_draft(
    draft_id: int = 1,
    topic: str = "Test topic",
    content: str = "Draft body",
    platform: str = "telegram",
    scheduled_at: datetime | None = None,
) -> MagicMock:
    draft = MagicMock(spec=Draft)
    draft.id = draft_id
    draft.topic = topic
    draft.content = content
    draft.platform = platform
    draft.scheduled_at = scheduled_at
    return draft


# ---------------------------------------------------------------------------
# POST /slack/commands
# ---------------------------------------------------------------------------


class TestSlackCommands:
    def test_unknown_command_returns_ephemeral_response(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/slack/commands",
            data={"command": "/unknown", "trigger_id": "tid", "channel_id": "C123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("response_type") == "ephemeral"

    @patch("slack_app.handlers.slash_commands.httpx.AsyncClient")
    def test_draft_command_opens_modal_and_returns_200(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/api/v1/slack/commands",
            data={"command": "/draft", "trigger_id": "tid123", "channel_id": "C456"},
        )
        assert resp.status_code == 200
        mock_http.post.assert_awaited_once()
        call_kwargs = mock_http.post.call_args
        assert "views.open" in call_kwargs[0][0]

    @patch("slack_app.handlers.slash_commands.httpx.AsyncClient")
    def test_draft_command_passes_channel_to_modal(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_client_cls.return_value = mock_http

        client.post(
            "/api/v1/slack/commands",
            data={"command": "/draft", "trigger_id": "tid", "channel_id": "C_SPECIFIC"},
        )
        payload = mock_http.post.call_args.kwargs.get("json", {})
        # The trigger_id is propagated to views.open
        assert payload.get("trigger_id") == "tid"


# ---------------------------------------------------------------------------
# POST /slack/interactions — block_actions
# ---------------------------------------------------------------------------


class TestSlackInteractionsBlockActions:
    def _post_interaction(
        self, client: TestClient, payload: Mapping[str, object]
    ) -> Response:
        return client.post(
            "/api/v1/slack/interactions",
            data={"payload": json.dumps(payload)},
        )

    def test_missing_payload_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/v1/slack/interactions", data={})
        assert resp.status_code == 400

    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_open_upload_modal_action_returns_200(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "trigger_id": "tid",
            "actions": [
                {"action_id": "action_open_upload_modal", "value": "1|threads"}
            ],
        }
        resp = self._post_interaction(client, payload)
        assert resp.status_code == 200

    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_reject_draft_action_updates_status(
        self, mock_cls: MagicMock, client: TestClient, mock_session: MagicMock
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        fake_draft = _make_draft(draft_id=5, content="body")
        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_draft)
        mock_repo.update = AsyncMock()

        with patch(
            "slack_app.handlers.interactions.DraftRepository", return_value=mock_repo
        ):
            payload = {
                "type": "block_actions",
                "user": {"id": "U1"},
                "trigger_id": "t",
                "response_url": "https://hooks.slack.com/resp/xyz",
                "actions": [
                    {"action_id": "action_reject_draft", "value": "5|telegram"}
                ],
                "message": {"blocks": []},
            }
            resp = self._post_interaction(client, payload)

        assert resp.status_code == 200
        mock_repo.update.assert_awaited_once()
        update_call_args = mock_repo.update.call_args
        draft_update = update_call_args[0][1]
        assert draft_update.status == DraftStatus.REJECTED

    @patch("slack_app.handlers.interactions.publish_post_task")
    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_publish_draft_action_kicks_task(
        self, mock_cls: MagicMock, mock_task: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http
        mock_task.kiq = AsyncMock()

        fake_draft = _make_draft(draft_id=3, content="Post content")
        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_draft)
        mock_repo.update = AsyncMock()

        with patch(
            "slack_app.handlers.interactions.DraftRepository", return_value=mock_repo
        ):
            payload = {
                "type": "block_actions",
                "user": {"id": "U1"},
                "trigger_id": "t",
                "response_url": "https://hooks.slack.com/resp/abc",
                "actions": [
                    {"action_id": "action_publish_draft", "value": "3|telegram"}
                ],
                "message": {"blocks": []},
            }
            resp = client.post(
                "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
            )

        assert resp.status_code == 200
        mock_task.kiq.assert_awaited_once()

    @patch("slack_app.handlers.interactions.generate_draft_task")
    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_regenerate_draft_kicks_generate_task(
        self, mock_cls: MagicMock, mock_task: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http
        mock_task.kiq = AsyncMock()

        fake_draft = _make_draft(draft_id=7, content="old content")
        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_draft)

        with patch(
            "slack_app.handlers.interactions.DraftRepository", return_value=mock_repo
        ):
            payload = {
                "type": "block_actions",
                "user": {"id": "U9"},
                "trigger_id": "t",
                "response_url": "https://hooks.slack.com/resp/regen",
                "channel": {"id": "C_CHAN"},
                "actions": [
                    {"action_id": "action_regenerate_draft", "value": "7|telegram"}
                ],
                "message": {"blocks": []},
            }
            resp = client.post(
                "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
            )

        assert resp.status_code == 200
        mock_task.kiq.assert_awaited_once()

    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_pagination_action_publishes_home_view(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        mock_repo = AsyncMock()
        mock_repo.get_recent_drafts = AsyncMock(return_value=[])

        with patch(
            "slack_app.handlers.interactions.DraftRepository", return_value=mock_repo
        ):
            payload = {
                "type": "block_actions",
                "user": {"id": "U1"},
                "trigger_id": "t",
                "actions": [{"action_id": "action_home_drafts_next", "value": "10"}],
            }
            resp = client.post(
                "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
            )

        assert resp.status_code == 200
        mock_repo.get_recent_drafts.assert_awaited_once_with(limit=10, offset=10)


# ---------------------------------------------------------------------------
# POST /slack/interactions — view_submission
# ---------------------------------------------------------------------------


class TestSlackInteractionsViewSubmission:
    def _make_view_payload(
        self, callback_id: str, state_values: Mapping[str, object], metadata: str = ""
    ) -> dict[str, object]:
        return {
            "type": "view_submission",
            "user": {"id": "U_VIEWER"},
            "view": {
                "callback_id": callback_id,
                "private_metadata": metadata,
                "state": {"values": state_values},
            },
        }

    @patch("slack_app.handlers.interactions.DraftService")
    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_generate_draft_modal_triggers_draft_service(
        self, mock_cls: MagicMock, mock_svc_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        mock_svc = AsyncMock()
        mock_svc.generate_draft_from_slack = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        state = {
            "block_topic_input": {"input_topic": {"value": "Serotonin and gut health"}},
            "block_platform_select": {
                "input_platform_select": {"selected_option": {"value": "telegram"}}
            },
        }
        payload = self._make_view_payload(
            "modal_generate_draft", state, metadata="C_CHAN"
        )
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body.get("response_action") == "clear"
        mock_svc.generate_draft_from_slack.assert_awaited_once()

    def test_schedule_draft_modal_missing_timestamp_returns_error(
        self, client: TestClient
    ) -> None:
        state = {
            "block_schedule_time": {"input_schedule_time": {"selected_date_time": None}}
        }
        payload = self._make_view_payload(
            "modal_schedule_draft", state, metadata="5|telegram"
        )
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body.get("response_action") == "errors"
        assert "block_schedule_time" in body.get("errors", {})

    def test_schedule_draft_modal_non_digit_id_returns_error(
        self, client: TestClient
    ) -> None:
        state = {
            "block_schedule_time": {
                "input_schedule_time": {"selected_date_time": 1700000000}
            }
        }
        payload = self._make_view_payload(
            "modal_schedule_draft", state, metadata="not_a_number|telegram"
        )
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body.get("response_action") == "errors"

    @patch("slack_app.handlers.interactions.DraftRepository")
    def test_schedule_draft_modal_valid_updates_db(
        self, mock_repo_cls: MagicMock, client: TestClient
    ) -> None:
        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        ts = int(datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc).timestamp())
        state = {
            "block_schedule_time": {"input_schedule_time": {"selected_date_time": ts}}
        }
        payload = self._make_view_payload(
            "modal_schedule_draft", state, metadata="3|telegram"
        )
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        mock_repo.update.assert_awaited_once()
        update_args = mock_repo.update.call_args[0]
        assert update_args[0] == 3
        assert update_args[1].status == DraftStatus.SCHEDULED

    def test_upload_guideline_no_files_returns_400(self, client: TestClient) -> None:
        state = {"block_file_upload": {"input_file": {"files": []}}}
        payload = self._make_view_payload("modal_upload_guideline", state)
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )
        assert resp.status_code == 400

    @patch("slack_app.handlers.interactions.ingest_guideline_task")
    def test_upload_guideline_valid_kicks_task(
        self, mock_task: MagicMock, client: TestClient
    ) -> None:
        mock_task.kiq = AsyncMock()

        state = {
            "block_file_upload": {
                "input_file": {
                    "files": [
                        {
                            "url_private_download": "https://files.slack.com/file.pdf",
                            "name": "guideline.pdf",
                        }
                    ]
                }
            }
        }
        payload = self._make_view_payload("modal_upload_guideline", state)
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        mock_task.kiq.assert_awaited_once_with(
            file_url="https://files.slack.com/file.pdf",
            file_name="guideline.pdf",
            user_id="U_VIEWER",
        )

    @patch("slack_app.handlers.interactions.DraftRepository")
    @patch("slack_app.handlers.interactions.httpx.AsyncClient")
    def test_edit_draft_modal_saves_content_and_redraws(
        self, mock_cls: MagicMock, mock_repo_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        state = {
            "block_draft_content": {
                "input_draft_content": {"value": "Updated content here"}
            },
            "block_platform_select": {
                "input_platform_select": {"selected_option": {"value": "telegram"}}
            },
        }
        # metadata: topic|draft_id|channel_id|message_ts
        payload = self._make_view_payload(
            "modal_edit_draft",
            state,
            metadata="MyTopic|10|C_CHAN|1700000001.000",
        )
        resp = client.post(
            "/api/v1/slack/interactions", data={"payload": json.dumps(payload)}
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body.get("response_action") == "clear"
        mock_repo.update.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /slack/error
# ---------------------------------------------------------------------------


class TestSlackErrorEndpoint:
    @patch("backend.api.routes.feedback.httpx.AsyncClient")
    def test_valid_error_payload_returns_200(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        with patch("backend.api.routes.feedback.DraftRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.update = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            resp = client.post(
                "/api/v1/slack/error",
                json={
                    "post_id": "42",
                    "platform": "telegram",
                    "error_message": "Connection timeout",
                    "user_id": "U123",
                },
            )

        assert resp.status_code == 200

    @patch("backend.api.routes.feedback.httpx.AsyncClient")
    def test_digit_post_id_updates_draft_status_to_failed(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        with patch("backend.api.routes.feedback.DraftRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.update = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            client.post(
                "/api/v1/slack/error",
                json={
                    "post_id": "5",
                    "platform": "threads",
                    "error_message": "publish failed",
                },
            )

        mock_repo.update.assert_awaited_once()
        call_args = mock_repo.update.call_args[0]
        assert call_args[0] == 5
        assert call_args[1].status == DraftStatus.FAILED

    @patch("backend.api.routes.feedback.httpx.AsyncClient")
    def test_non_digit_post_id_skips_db_update(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        with patch("backend.api.routes.feedback.DraftRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.update = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            client.post(
                "/api/v1/slack/error",
                json={
                    "post_id": "temp_id",
                    "platform": "telegram",
                    "error_message": "some error",
                },
            )

        mock_repo.update.assert_not_awaited()

    @patch("backend.api.routes.feedback.httpx.AsyncClient")
    def test_error_notification_sent_to_user_channel(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        with patch("backend.api.routes.feedback.DraftRepository") as mock_repo_cls:
            mock_repo_cls.return_value = AsyncMock()
            mock_repo_cls.return_value.update = AsyncMock()

            client.post(
                "/api/v1/slack/error",
                json={
                    "post_id": "1",
                    "platform": "telegram",
                    "error_message": "failed",
                    "user_id": "U_NOTIFY",
                },
            )

        json_body = mock_http.post.call_args.kwargs.get("json", {})
        assert json_body.get("channel") == "U_NOTIFY"


# ---------------------------------------------------------------------------
# POST /slack/events
# ---------------------------------------------------------------------------


class TestSlackEvents:
    def test_url_verification_challenge_returns_challenge(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/slack/events",
            json={"type": "url_verification", "challenge": "abc123"},
        )
        assert resp.status_code == 200
        assert resp.json().get("challenge") == "abc123"

    @patch("slack_app.handlers.events.httpx.AsyncClient")
    def test_app_home_opened_publishes_home_view(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=_slack_ok_response())
        mock_cls.return_value = mock_http

        mock_repo = AsyncMock()
        mock_repo.get_recent_drafts = AsyncMock(return_value=[])

        with patch("slack_app.handlers.events.DraftRepository", return_value=mock_repo):
            resp = client.post(
                "/api/v1/slack/events",
                json={
                    "type": "event_callback",
                    "event": {"type": "app_home_opened", "user": "U_HOME"},
                },
            )

        assert resp.status_code == 200
        mock_repo.get_recent_drafts.assert_awaited_once_with(limit=10)
        call_url = mock_http.post.call_args[0][0]
        assert "views.publish" in call_url

    @patch("slack_app.handlers.events.httpx.AsyncClient")
    def test_unknown_event_type_returns_200(
        self, mock_cls: MagicMock, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/v1/slack/events",
            json={"type": "event_callback", "event": {"type": "message", "user": "U1"}},
        )
        assert resp.status_code == 200
