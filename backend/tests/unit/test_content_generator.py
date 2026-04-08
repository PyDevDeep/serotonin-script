"""
Tests for backend.services.content_generator.

Coverage:
- JudgeFailedError: attributes, message, inheritance
- ContentGenerator._judge_limited: pass, fail, malformed JSON, LLM exception
- ContentGenerator.generate_draft:
    * is_limited=False → single generation, no judge called
    * is_limited=True, judge passes on first attempt → returns result
    * is_limited=True, judge fails once then passes → retry injection applied
    * is_limited=True, judge fails all retries → JudgeFailedError raised
    * ОБМЕЖЕНИЙ status detection (with quotes/whitespace edge cases)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.content_generator import ContentGenerator, JudgeFailedError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_style_matcher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_fact_checker() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def generator(
    mock_llm_router: AsyncMock,
    mock_style_matcher: AsyncMock,
    mock_fact_checker: AsyncMock,
) -> ContentGenerator:
    return ContentGenerator(
        llm_router=mock_llm_router,  # type: ignore[arg-type]
        style_matcher=mock_style_matcher,  # type: ignore[arg-type]
        fact_checker=mock_fact_checker,  # type: ignore[arg-type]
    )


def _llm_response(content: str, provider: str = "anthropic") -> MagicMock:
    """Build a minimal mock LLM response."""
    resp = MagicMock()
    resp.message.content = content
    resp.provider = provider
    return resp


# ---------------------------------------------------------------------------
# TestJudgeFailedError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJudgeFailedError:
    """JudgeFailedError stores topic, attempts, draft and has correct message."""

    def test_attributes_stored(self) -> None:
        err = JudgeFailedError(topic="anxiety", attempts=3, draft="bad draft")
        assert err.topic == "anxiety"
        assert err.attempts == 3
        assert err.draft == "bad draft"

    def test_message_contains_attempts_and_topic(self) -> None:
        err = JudgeFailedError(topic="migraine", attempts=2, draft="")
        assert "2" in str(err)
        assert "migraine" in str(err)

    def test_is_exception_subclass(self) -> None:
        err = JudgeFailedError(topic="x", attempts=1, draft="y")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(JudgeFailedError) as exc_info:
            raise JudgeFailedError(topic="stress", attempts=1, draft="text")
        assert exc_info.value.topic == "stress"


# ---------------------------------------------------------------------------
# TestJudgeLimited
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJudgeLimited:
    """_judge_limited parses LLM JSON response into pass/violations dict."""

    @pytest.mark.asyncio
    async def test_pass_true_returned(
        self, generator: ContentGenerator, mock_llm_router: AsyncMock
    ) -> None:
        mock_llm_router.achat_with_fallback.return_value = _llm_response(
            '{"pass": true, "violations": []}'
        )
        result = await generator._judge_limited("post text", "anxiety", "ОБМЕЖЕНИЙ")
        assert result["pass"] is True
        assert result["violations"] == []

    @pytest.mark.asyncio
    async def test_pass_false_with_violations(
        self, generator: ContentGenerator, mock_llm_router: AsyncMock
    ) -> None:
        payload = '{"pass": false, "violations": [{"sentence": "bad line", "reason": "clinical claim"}]}'
        mock_llm_router.achat_with_fallback.return_value = _llm_response(payload)
        result = await generator._judge_limited("post", "topic", "ОБМЕЖЕНИЙ")  # type: ignore[misc]
        assert result["pass"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["sentence"] == "bad line"

    @pytest.mark.asyncio
    async def test_markdown_code_block_stripped(
        self, generator: ContentGenerator, mock_llm_router: AsyncMock
    ) -> None:
        payload = '```json\n{"pass": true, "violations": []}\n```'
        mock_llm_router.achat_with_fallback.return_value = _llm_response(payload)
        result = await generator._judge_limited("post", "topic", "ОБМЕЖЕНИЙ")  # type: ignore[misc]
        assert result["pass"] is True

    @pytest.mark.asyncio
    async def test_malformed_json_returns_fail_with_error_reason(
        self, generator: ContentGenerator, mock_llm_router: AsyncMock
    ) -> None:
        mock_llm_router.achat_with_fallback.return_value = _llm_response("not json")
        result = await generator._judge_limited("post", "topic", "ОБМЕЖЕНИЙ")  # type: ignore[misc]
        assert result["pass"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["sentence"] == "system"

    @pytest.mark.asyncio
    async def test_llm_exception_returns_fail(
        self, generator: ContentGenerator, mock_llm_router: AsyncMock
    ) -> None:
        mock_llm_router.achat_with_fallback.side_effect = RuntimeError("LLM error")
        result = await generator._judge_limited("post", "topic", "ОБМЕЖЕНИЙ")  # type: ignore[misc]
        assert result["pass"] is False


# ---------------------------------------------------------------------------
# TestGenerateDraft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateDraft:
    """generate_draft orchestrates style, fact context, generation, and judge."""

    @pytest.mark.asyncio
    async def test_not_limited_status_skips_judge(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """ПОВНИЙ status → no judge call, result returned directly."""
        mock_style_matcher.get_style_context.return_value = "style ctx"
        mock_fact_checker.get_medical_context.return_value = ("medical ctx", "ПОВНИЙ")
        mock_llm_router.achat_with_fallback.return_value = _llm_response(
            "Generated post"
        )

        result = await generator.generate_draft("anxiety", "telegram")
        assert result == "Generated post"
        # Judge never called → achat_with_fallback called exactly once (generation only)
        mock_llm_router.achat_with_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_limited_status_judge_passes_first_attempt(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """ОБМЕЖЕНИЙ + judge passes immediately → single generation + single judge call."""
        mock_style_matcher.get_style_context.return_value = "style"
        mock_fact_checker.get_medical_context.return_value = (
            "limited ctx",
            "ОБМЕЖЕНИЙ",
        )

        generation_response = _llm_response("Draft text")
        judge_response = _llm_response('{"pass": true, "violations": []}')
        mock_llm_router.achat_with_fallback.side_effect = [
            generation_response,
            judge_response,
        ]

        result = await generator.generate_draft("stress", "twitter", max_retries=1)
        assert result == "Draft text"
        assert mock_llm_router.achat_with_fallback.call_count == 2

    @pytest.mark.asyncio
    async def test_limited_status_judge_fails_then_passes(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """ОБМЕЖЕНИЙ + judge fails attempt 0, passes attempt 1 → returns second draft."""
        mock_style_matcher.get_style_context.return_value = "style"
        mock_fact_checker.get_medical_context.return_value = (
            "limited ctx",
            "ОБМЕЖЕНИЙ",
        )

        fail_judge = (
            '{"pass": false, "violations": [{"sentence": "bad", "reason": "clinical"}]}'
        )
        pass_judge = '{"pass": true, "violations": []}'

        responses = [
            _llm_response("Draft attempt 1"),
            _llm_response(fail_judge),  # judge fails
            _llm_response("Draft attempt 2"),
            _llm_response(pass_judge),  # judge passes
        ]
        mock_llm_router.achat_with_fallback.side_effect = responses

        result = await generator.generate_draft("depression", "threads", max_retries=1)
        assert result == "Draft attempt 2"

    @pytest.mark.asyncio
    async def test_judge_fails_all_retries_raises_judge_failed_error(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """ОБМЕЖЕНИЙ + judge fails all attempts → JudgeFailedError raised with last draft."""
        mock_style_matcher.get_style_context.return_value = "style"
        mock_fact_checker.get_medical_context.return_value = (
            "limited ctx",
            "ОБМЕЖЕНИЙ",
        )

        fail_judge = '{"pass": false, "violations": [{"sentence": "s", "reason": "r"}]}'
        responses = [
            _llm_response("Draft attempt 1"),
            _llm_response(fail_judge),
            _llm_response("Draft attempt 2"),
            _llm_response(fail_judge),
        ]
        mock_llm_router.achat_with_fallback.side_effect = responses

        with pytest.raises(JudgeFailedError) as exc_info:
            await generator.generate_draft("burnout", "telegram", max_retries=1)

        assert exc_info.value.topic == "burnout"
        assert exc_info.value.attempts == 2
        assert exc_info.value.draft == "Draft attempt 2"

    @pytest.mark.asyncio
    async def test_status_with_quotes_treated_as_limited(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """Status string with surrounding quotes still triggers limited path."""
        mock_style_matcher.get_style_context.return_value = "style"
        # Status wrapped in quotes — edge case from normalize logic
        mock_fact_checker.get_medical_context.return_value = ("ctx", "'ОБМЕЖЕНИЙ'")

        generation_response = _llm_response("Draft")
        judge_response = _llm_response('{"pass": true, "violations": []}')
        mock_llm_router.achat_with_fallback.side_effect = [
            generation_response,
            judge_response,
        ]

        result = await generator.generate_draft("topic", "twitter", max_retries=1)
        assert result == "Draft"
        # Judge WAS called because status normalized to ОБМЕЖЕНИЙ
        assert mock_llm_router.achat_with_fallback.call_count == 2

    @pytest.mark.asyncio
    async def test_source_url_passed_to_fact_checker(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """source_url is forwarded to fact_checker.get_medical_context."""
        mock_style_matcher.get_style_context.return_value = "style"
        mock_fact_checker.get_medical_context.return_value = ("ctx", "ПОВНИЙ")
        mock_llm_router.achat_with_fallback.return_value = _llm_response("Post")

        await generator.generate_draft(
            "anxiety", "telegram", source_url="https://pubmed.org/123"
        )
        mock_fact_checker.get_medical_context.assert_called_once_with(
            "anxiety", source_url="https://pubmed.org/123"
        )

    @pytest.mark.asyncio
    async def test_llm_generation_returns_empty_string_handled(
        self,
        generator: ContentGenerator,
        mock_llm_router: AsyncMock,
        mock_style_matcher: AsyncMock,
        mock_fact_checker: AsyncMock,
    ) -> None:
        """LLM returning None content falls back to empty string (no AttributeError)."""
        mock_style_matcher.get_style_context.return_value = "style"
        mock_fact_checker.get_medical_context.return_value = ("ctx", "ПОВНИЙ")

        resp = MagicMock()
        resp.message.content = None
        mock_llm_router.achat_with_fallback.return_value = resp

        result = await generator.generate_draft("topic", "telegram")
        assert result == ""
