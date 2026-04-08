"""
Tests for backend.services.style_matcher.StyleMatcher.

Coverage:
- get_style_context: no nodes → fallback string
- get_style_context: nodes returned → whitespace normalization, formatting
- Normalization rules: \\r\\n, trailing spaces, leading spaces after \\n, 3+ newlines
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.style_matcher import StyleMatcher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retriever() -> AsyncMock:
    """Mock RetrieverProtocol."""
    return AsyncMock()


@pytest.fixture
def matcher(mock_retriever: AsyncMock) -> StyleMatcher:
    """StyleMatcher instance with mocked retriever."""
    return StyleMatcher(retriever=mock_retriever)


def _make_mock_node(content: str) -> MagicMock:
    """Create a mock NodeWithScore that returns given content."""
    node = MagicMock()
    node.get_content.return_value = content
    return node


# ---------------------------------------------------------------------------
# TestStyleMatcherGetStyleContext
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStyleMatcherGetStyleContext:
    """get_style_context returns formatted style examples or fallback."""

    @pytest.mark.asyncio
    async def test_no_nodes_returns_fallback_string(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = []
        result = await matcher.get_style_context("anxiety")
        assert result == "No style context found."

    @pytest.mark.asyncio
    async def test_single_node_formatted_with_header(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [_make_mock_node("Sample style text.")]
        result = await matcher.get_style_context("depression")
        assert "--- Приклад стилю 1 ---" in result
        assert "Sample style text." in result

    @pytest.mark.asyncio
    async def test_multiple_nodes_numbered_sequentially(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        nodes = [_make_mock_node(f"text {i}") for i in range(1, 4)]
        mock_retriever.retrieve.return_value = nodes
        result = await matcher.get_style_context("stress")

        assert "--- Приклад стилю 1 ---" in result
        assert "--- Приклад стилю 2 ---" in result
        assert "--- Приклад стилю 3 ---" in result

    @pytest.mark.asyncio
    async def test_multiple_nodes_joined_with_double_newline(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        nodes = [_make_mock_node("first"), _make_mock_node("second")]
        mock_retriever.retrieve.return_value = nodes
        result = await matcher.get_style_context("topic")
        assert "\n\n" in result

    @pytest.mark.asyncio
    async def test_retriever_called_with_topic(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = []
        await matcher.get_style_context("migraine")
        mock_retriever.retrieve.assert_called_once_with("migraine")

    @pytest.mark.asyncio
    async def test_crlf_normalized(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [
            _make_mock_node("line1\r\nline2\rline3")
        ]
        result = await matcher.get_style_context("topic")
        assert "\r" not in result

    @pytest.mark.asyncio
    async def test_trailing_spaces_before_newline_stripped(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [_make_mock_node("text   \nnext line")]
        result = await matcher.get_style_context("topic")
        # trailing spaces before \n should be removed
        assert "   \n" not in result

    @pytest.mark.asyncio
    async def test_leading_spaces_after_newline_stripped(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [_make_mock_node("line1\n   indented")]
        result = await matcher.get_style_context("topic")
        assert "\n   " not in result

    @pytest.mark.asyncio
    async def test_triple_newlines_collapsed_to_double(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [_make_mock_node("para1\n\n\n\npara2")]
        result = await matcher.get_style_context("topic")
        assert "\n\n\n" not in result

    @pytest.mark.asyncio
    async def test_content_stripped(
        self, matcher: StyleMatcher, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = [_make_mock_node("   padded content   ")]
        result = await matcher.get_style_context("topic")
        # Content should be stripped before embedding in header
        assert "   padded content   " not in result
        assert "padded content" in result
