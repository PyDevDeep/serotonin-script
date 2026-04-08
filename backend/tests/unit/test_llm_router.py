from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import BadRequestError
from llama_index.core.llms import ChatMessage, ChatResponse

from backend.integrations.llm.router import LLMResponse, LLMRouter


@pytest.fixture
def mock_llms():
    primary = MagicMock()
    primary.achat = AsyncMock()
    fallback = MagicMock()
    fallback.achat = AsyncMock()
    cheap = MagicMock()
    cheap.achat = AsyncMock()
    return primary, fallback, cheap


@pytest.fixture
def router(mock_llms):
    primary, fallback, cheap = mock_llms
    with (
        patch(
            "backend.integrations.llm.router.get_anthropic_llm", return_value=primary
        ),
        patch("backend.integrations.llm.router.get_openai_llm", return_value=fallback),
        patch(
            "backend.integrations.llm.router.get_cheap_openai_llm", return_value=cheap
        ),
    ):
        r = LLMRouter()
    r.primary_llm = primary
    r.fallback_llm = fallback
    r.cheap_llm = cheap
    return r


def make_messages(content: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=content)]


def make_chat_response(content: str = "ok") -> ChatResponse:
    msg = ChatMessage(role="assistant", content=content)
    return ChatResponse(message=msg)


# --- LLMResponse ---


def test_llm_response_message():
    resp = make_chat_response("hello")
    wrapper = LLMResponse(response=resp, provider="anthropic")
    assert wrapper.message.content == "hello"
    assert wrapper.provider == "anthropic"


# --- _calculate_length ---


def test_calculate_length_empty(router):
    assert router._calculate_length([]) == 0


def test_calculate_length_single(router):
    msgs = make_messages("abc")
    assert router._calculate_length(msgs) == 3


def test_calculate_length_multiple(router):
    msgs = [
        ChatMessage(role="user", content="ab"),
        ChatMessage(role="assistant", content="cde"),
    ]
    assert router._calculate_length(msgs) == 5


def test_calculate_length_none_content(router):
    msgs = [ChatMessage(role="user", content=None)]
    assert router._calculate_length(msgs) == 0


# --- cost routing (above threshold) ---


@pytest.mark.asyncio
async def test_cost_routing_uses_cheap_llm(router):
    cheap_response = make_chat_response("cheap answer")
    router.cheap_llm.achat.return_value = cheap_response

    long_content = "x" * 10_000
    primary_msgs = make_messages(long_content)
    fallback_msgs = make_messages("short fallback")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100
        result = await router.achat_with_fallback(primary_msgs, fallback_msgs)

    assert result.provider == "openai"
    assert result.message.content == "cheap answer"
    router.cheap_llm.achat.assert_called_once_with(fallback_msgs)
    router.primary_llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_cost_routing_cheap_llm_failure_raises(router):
    router.cheap_llm.achat.side_effect = RuntimeError("overloaded")

    long_content = "x" * 10_000
    primary_msgs = make_messages(long_content)
    fallback_msgs = make_messages("short fallback")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100
        with pytest.raises(RuntimeError, match="overloaded"):
            await router.achat_with_fallback(primary_msgs, fallback_msgs)


# --- primary success ---


@pytest.mark.asyncio
async def test_primary_success_returns_anthropic(router):
    primary_response = make_chat_response("primary answer")
    router.primary_llm.achat.return_value = primary_response

    msgs = make_messages("hello")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100_000
        result = await router.achat_with_fallback(msgs, msgs)

    assert result.provider == "anthropic"
    assert result.message.content == "primary answer"
    router.fallback_llm.achat.assert_not_called()


# --- BadRequestError: no fallback ---


@pytest.mark.asyncio
async def test_bad_request_error_no_fallback(router):
    err = BadRequestError.__new__(BadRequestError)
    err.message = "bad request"
    err.body = {}
    router.primary_llm.achat.side_effect = BadRequestError(
        message="bad request", response=MagicMock(status_code=400), body={}
    )

    msgs = make_messages("hello")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100_000
        with pytest.raises(BadRequestError):
            await router.achat_with_fallback(msgs, msgs)

    router.fallback_llm.achat.assert_not_called()


# --- primary failure → fallback success ---


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_openai(router):
    router.primary_llm.achat.side_effect = RuntimeError("529 Overloaded")
    fallback_response = make_chat_response("fallback answer")
    router.fallback_llm.achat.return_value = fallback_response

    msgs = make_messages("hello")
    fallback_msgs = make_messages("fallback prompt")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100_000
        result = await router.achat_with_fallback(msgs, fallback_msgs)

    assert result.provider == "openai"
    assert result.message.content == "fallback answer"
    router.fallback_llm.achat.assert_called_once_with(fallback_msgs)


# --- primary failure + fallback failure → raises ---


@pytest.mark.asyncio
async def test_both_providers_fail_raises(router):
    router.primary_llm.achat.side_effect = RuntimeError("primary down")
    router.fallback_llm.achat.side_effect = RuntimeError("fallback down")

    msgs = make_messages("hello")

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 100_000
        with pytest.raises(RuntimeError, match="fallback down"):
            await router.achat_with_fallback(msgs, msgs)


# --- threshold boundary ---


@pytest.mark.asyncio
async def test_exactly_at_threshold_uses_primary(router):
    primary_response = make_chat_response("primary")
    router.primary_llm.achat.return_value = primary_response

    # exactly at threshold — should NOT trigger cost routing (> not >=)
    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 5
        msgs = make_messages("hello")  # len == 5
        result = await router.achat_with_fallback(msgs, msgs)

    assert result.provider == "anthropic"
    router.cheap_llm.achat.assert_not_called()


@pytest.mark.asyncio
async def test_one_above_threshold_uses_cheap(router):
    cheap_response = make_chat_response("cheap")
    router.cheap_llm.achat.return_value = cheap_response

    with patch("backend.integrations.llm.router.settings") as mock_settings:
        mock_settings.LLM_COST_THRESHOLD_CHARS = 5
        msgs = make_messages("hello!")  # len == 6
        result = await router.achat_with_fallback(msgs, msgs)

    assert result.provider == "openai"
    router.primary_llm.achat.assert_not_called()
