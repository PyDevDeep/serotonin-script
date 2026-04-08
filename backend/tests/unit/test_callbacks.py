"""
Tests for backend.workers.callbacks.

Coverage:
- _send_slack_message: missing token (abort), successful post, api ok=False, network error
- notify_slack_on_complete: payload structure, delegates to _send_slack_message
- notify_slack_on_failure: payload structure (blocks), delegates to _send_slack_message
- notify_slack_upload_success: sends DM to user_id with correct text
- notify_slack_upload_failure: sends DM to user_id with error details
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.workers.callbacks import (
    _send_slack_message,
    notify_slack_on_complete,
    notify_slack_on_failure,
    notify_slack_upload_failure,
    notify_slack_upload_success,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings_with_token():
    """Settings with a valid SLACK_BOT_TOKEN."""
    token_mock = MagicMock()
    token_mock.get_secret_value.return_value = "xoxb-test-token"
    settings_mock = MagicMock()
    settings_mock.SLACK_BOT_TOKEN = token_mock
    return settings_mock


@pytest.fixture
def mock_settings_no_token():
    """Settings with SLACK_BOT_TOKEN = None."""
    settings_mock = MagicMock()
    settings_mock.SLACK_BOT_TOKEN = None
    return settings_mock


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ok": True}
    return resp


def _not_ok_response(error: str = "channel_not_found") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ok": False, "error": error}
    return resp


# ---------------------------------------------------------------------------
# _send_slack_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendSlackMessage:
    @pytest.mark.asyncio
    async def test_missing_token_aborts_without_http_call(
        self, mock_settings_no_token
    ) -> None:
        """No token → logs error, returns immediately, no HTTP request made."""
        with patch("backend.workers.callbacks.settings", mock_settings_no_token):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                await _send_slack_message({"channel": "C123", "text": "hi"})

                mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_post_calls_api_once(
        self, mock_settings_with_token
    ) -> None:
        """Valid token + ok=True response: API called exactly once."""
        mock_post = AsyncMock(return_value=_ok_response())

        with patch("backend.workers.callbacks.settings", mock_settings_with_token):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=mock_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await _send_slack_message({"channel": "C123", "text": "hello"})

                mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_returns_ok_false_logs_error(
        self, mock_settings_with_token
    ) -> None:
        """ok=False in Slack response should be handled without raising."""
        mock_post = AsyncMock(return_value=_not_ok_response("not_in_channel"))

        with patch("backend.workers.callbacks.settings", mock_settings_with_token):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=mock_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                # Must not raise
                await _send_slack_message({"channel": "C123", "text": "hello"})

    @pytest.mark.asyncio
    async def test_network_error_does_not_propagate(
        self, mock_settings_with_token
    ) -> None:
        """Connection errors are caught and swallowed (callback must not crash worker)."""
        import httpx as _httpx

        mock_post = AsyncMock(side_effect=_httpx.ConnectError("refused"))

        with patch("backend.workers.callbacks.settings", mock_settings_with_token):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=mock_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await _send_slack_message({"channel": "C123", "text": "hello"})

    @pytest.mark.asyncio
    async def test_bearer_token_set_in_header(self, mock_settings_with_token) -> None:
        """Authorization header contains the Bearer token value."""
        captured_headers = {}
        ok_resp = _ok_response()

        async def capture_post(url, headers, json):
            captured_headers.update(headers)
            return ok_resp

        with patch("backend.workers.callbacks.settings", mock_settings_with_token):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=capture_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await _send_slack_message({"channel": "C123", "text": "x"})

        assert captured_headers.get("Authorization") == "Bearer xoxb-test-token"


# ---------------------------------------------------------------------------
# notify_slack_on_complete
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifySlackOnComplete:
    @pytest.mark.asyncio
    async def test_calls_send_slack_message_with_correct_channel(self) -> None:
        """Completion notification targets the correct channel_id."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            with patch("backend.workers.callbacks.build_draft_card", return_value=[]):
                await notify_slack_on_complete(
                    user_id="U111",
                    channel_id="C999",
                    draft="Draft text here",
                    topic="Серотонін",
                    draft_id="draft-42",
                    platform="telegram",
                    is_valid=True,
                )

                mock_send.assert_called_once()
                payload = mock_send.call_args.args[0]
                assert payload["channel"] == "C999"

    @pytest.mark.asyncio
    async def test_fallback_text_contains_topic(self) -> None:
        """Fallback text must include the topic for accessibility."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            with patch("backend.workers.callbacks.build_draft_card", return_value=[]):
                await notify_slack_on_complete(
                    user_id="U111",
                    channel_id="C999",
                    draft="Draft text",
                    topic="Серотонін та депресія",
                    draft_id="draft-1",
                    platform="twitter",
                )

                payload = mock_send.call_args.args[0]
                assert "Серотонін та депресія" in payload["text"]

    @pytest.mark.asyncio
    async def test_is_valid_false_passed_to_build_draft_card(self) -> None:
        """is_valid=False flag must be forwarded to build_draft_card."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ):
            with patch(
                "backend.workers.callbacks.build_draft_card", return_value=[]
            ) as mock_build:
                await notify_slack_on_complete(
                    user_id="U1",
                    channel_id="C1",
                    draft="text",
                    topic="topic",
                    draft_id="d1",
                    platform="telegram",
                    is_valid=False,
                )

                call_kwargs = mock_build.call_args.kwargs
                assert call_kwargs.get("is_valid") is False


# ---------------------------------------------------------------------------
# notify_slack_on_failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifySlackOnFailure:
    @pytest.mark.asyncio
    async def test_calls_send_slack_message_with_correct_channel(self) -> None:
        """Failure notification targets the correct channel_id."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            await notify_slack_on_failure(
                user_id="U222",
                channel_id="C888",
                error_msg="LLM timeout",
                topic="Anxiety",
            )

            mock_send.assert_called_once()
            payload = mock_send.call_args.args[0]
            assert payload["channel"] == "C888"

    @pytest.mark.asyncio
    async def test_payload_contains_blocks(self) -> None:
        """Failure notification always includes a blocks list."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            await notify_slack_on_failure(
                user_id="U222",
                channel_id="C888",
                error_msg="timeout",
                topic="topic",
            )

            payload = mock_send.call_args.args[0]
            assert isinstance(payload.get("blocks"), list)
            assert len(payload["blocks"]) == 2  # header + section

    @pytest.mark.asyncio
    async def test_error_msg_in_block_text(self) -> None:
        """Error message text must appear somewhere in the blocks payload."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            await notify_slack_on_failure(
                user_id="U222",
                channel_id="C888",
                error_msg="Connection refused at line 42",
                topic="Mood",
            )

            payload = mock_send.call_args.args[0]
            section_text = payload["blocks"][1]["text"]["text"]
            assert "Connection refused at line 42" in section_text

    @pytest.mark.asyncio
    async def test_fallback_text_contains_topic(self) -> None:
        """Fallback text must include the topic."""
        with patch(
            "backend.workers.callbacks._send_slack_message", new_callable=AsyncMock
        ) as mock_send:
            await notify_slack_on_failure(
                user_id="U1",
                channel_id="C1",
                error_msg="err",
                topic="Кофеїн",
            )

            payload = mock_send.call_args.args[0]
            assert "Кофеїн" in payload["text"]


# ---------------------------------------------------------------------------
# notify_slack_upload_success
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifySlackUploadSuccess:
    @pytest.mark.asyncio
    async def test_posts_to_user_id_channel(self) -> None:
        """DM channel is user_id, not a separate channel_id."""
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "xoxb-token"
        settings_mock = MagicMock()
        settings_mock.SLACK_BOT_TOKEN = token_mock

        captured = {}

        async def capture_post(url, headers, json):
            captured["json"] = json
            return MagicMock()

        with patch("backend.workers.callbacks.settings", settings_mock):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=capture_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await notify_slack_upload_success(
                    user_id="U777", file_name="guideline.pdf"
                )

        assert captured["json"]["channel"] == "U777"

    @pytest.mark.asyncio
    async def test_message_contains_file_name(self) -> None:
        """Success message text must include the file name."""
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "xoxb-token"
        settings_mock = MagicMock()
        settings_mock.SLACK_BOT_TOKEN = token_mock

        captured = {}

        async def capture_post(url, headers, json):
            captured["json"] = json
            return MagicMock()

        with patch("backend.workers.callbacks.settings", settings_mock):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=capture_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await notify_slack_upload_success(
                    user_id="U777", file_name="clinical_trial.pdf"
                )

        assert "clinical_trial.pdf" in captured["json"]["text"]


# ---------------------------------------------------------------------------
# notify_slack_upload_failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifySlackUploadFailure:
    @pytest.mark.asyncio
    async def test_posts_to_user_id_channel(self) -> None:
        """Failure DM targets user_id as channel."""
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "xoxb-token"
        settings_mock = MagicMock()
        settings_mock.SLACK_BOT_TOKEN = token_mock

        captured = {}

        async def capture_post(url, headers, json):
            captured["json"] = json
            return MagicMock()

        with patch("backend.workers.callbacks.settings", settings_mock):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=capture_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await notify_slack_upload_failure(
                    user_id="U888",
                    file_name="bad_file.pdf",
                    error_msg="Unsupported format",
                )

        assert captured["json"]["channel"] == "U888"

    @pytest.mark.asyncio
    async def test_message_contains_file_name_and_error(self) -> None:
        """Failure message must include both file_name and error_msg."""
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "xoxb-token"
        settings_mock = MagicMock()
        settings_mock.SLACK_BOT_TOKEN = token_mock

        captured = {}

        async def capture_post(url, headers, json):
            captured["json"] = json
            return MagicMock()

        with patch("backend.workers.callbacks.settings", settings_mock):
            with patch(
                "backend.workers.callbacks.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(post=capture_post)
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                await notify_slack_upload_failure(
                    user_id="U888",
                    file_name="protocol.pdf",
                    error_msg="PDF parse failed at page 3",
                )

        text = captured["json"]["text"]
        assert "protocol.pdf" in text
        assert "PDF parse failed at page 3" in text
