"""
Tests for backend.rag.indexing.chunking module.

Covers:
- chunk_documents: empty input, MD separator routing, SentenceSplitter routing, mixed docs
- _is_post_separated: boundary detection for '---' separators
- _split_by_separator: correct splitting, metadata propagation, empty part filtering
"""

from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import Document, TextNode

from backend.rag.indexing.chunking import (
    _is_post_separated,
    _split_by_separator,
    chunk_documents,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plain_doc() -> Document:
    """Document without '---' separator — processed by SentenceSplitter."""
    return Document(
        text="This is a plain text document without separators.",
        metadata={"src": "plain"},
    )


@pytest.fixture
def separated_doc() -> Document:
    """Document with '---' separator — processed by _split_by_separator."""
    return Document(
        text="Post one content\n---\nPost two content\n---\nPost three content",
        metadata={"src": "posts"},
    )


@pytest.fixture
def leading_separator_doc() -> Document:
    """Document whose text starts with '---\\n' — also treated as post-separated."""
    return Document(text="---\nOnly one post here", metadata={"src": "leading"})


# ---------------------------------------------------------------------------
# _is_post_separated
# ---------------------------------------------------------------------------


class TestIsPostSeparated:
    """Tests for the _is_post_separated helper."""

    def test_returns_true_for_inline_separator(self, separated_doc: Document) -> None:
        assert _is_post_separated(separated_doc) is True

    def test_returns_true_for_leading_separator(
        self, leading_separator_doc: Document
    ) -> None:
        assert _is_post_separated(leading_separator_doc) is True

    def test_returns_false_for_plain_text(self, plain_doc: Document) -> None:
        assert _is_post_separated(plain_doc) is False

    def test_returns_false_for_single_dash(self) -> None:
        doc = Document(text="Just a - single dash line")
        assert _is_post_separated(doc) is False

    def test_returns_false_for_triple_dash_no_newline(self) -> None:
        # '---' without surrounding newlines must not trigger
        doc = Document(text="text---more text")
        assert _is_post_separated(doc) is False

    def test_returns_false_for_empty_text(self) -> None:
        doc = Document(text="")
        assert _is_post_separated(doc) is False


# ---------------------------------------------------------------------------
# _split_by_separator
# ---------------------------------------------------------------------------


class TestSplitBySeparator:
    """Tests for _split_by_separator helper."""

    def test_splits_into_correct_number_of_nodes(self, separated_doc: Document) -> None:
        nodes = _split_by_separator(separated_doc)
        assert len(nodes) == 3

    def test_all_nodes_are_text_nodes(self, separated_doc: Document) -> None:
        nodes = _split_by_separator(separated_doc)
        assert all(isinstance(n, TextNode) for n in nodes)

    def test_node_text_matches_parts(self, separated_doc: Document) -> None:
        nodes = _split_by_separator(separated_doc)
        texts = [n.text for n in nodes]
        assert "Post one content" in texts
        assert "Post two content" in texts
        assert "Post three content" in texts

    def test_metadata_copied_to_all_nodes(self, separated_doc: Document) -> None:
        nodes = _split_by_separator(separated_doc)
        for node in nodes:
            assert node.metadata == {"src": "posts"}

    def test_metadata_copy_is_independent(self, separated_doc: Document) -> None:
        """Mutating one node's metadata must not affect others."""
        nodes = _split_by_separator(separated_doc)
        nodes[0].metadata["injected"] = "value"
        assert "injected" not in nodes[1].metadata

    def test_filters_empty_parts_after_split(self) -> None:
        """Trailing or double separators must not produce empty nodes."""
        doc = Document(text="Part A\n---\n\n---\nPart B\n---\n")
        nodes = _split_by_separator(doc)
        assert len(nodes) == 2
        assert all(n.text for n in nodes)

    def test_single_part_returns_one_node(self) -> None:
        doc = Document(text="Only content, no separator", metadata={})
        nodes = _split_by_separator(doc)
        assert len(nodes) == 1
        assert nodes[0].text == "Only content, no separator"

    def test_custom_separator(self) -> None:
        doc = Document(text="A===B===C", metadata={})
        nodes = _split_by_separator(doc, separator="===")
        assert len(nodes) == 3


# ---------------------------------------------------------------------------
# chunk_documents
# ---------------------------------------------------------------------------


class TestChunkDocuments:
    """Tests for the main chunk_documents entry point."""

    def test_returns_empty_list_for_no_documents(self) -> None:
        assert chunk_documents([]) == []

    def test_separated_docs_bypass_sentence_splitter(
        self, separated_doc: Document
    ) -> None:
        """MD-separated docs must go through _split_by_separator, not SentenceSplitter."""
        with patch(
            "backend.rag.indexing.chunking.SentenceSplitter"
        ) as mock_splitter_cls:
            nodes = chunk_documents([separated_doc])
            mock_splitter_cls.assert_not_called()
        assert len(nodes) == 3

    def test_plain_docs_use_sentence_splitter(self, plain_doc: Document) -> None:
        fake_node = MagicMock()
        fake_node.text = "chunk"
        with patch("backend.rag.indexing.chunking.SentenceSplitter") as mock_cls:
            instance = mock_cls.return_value
            instance.get_nodes_from_documents.return_value = [fake_node]
            nodes = chunk_documents([plain_doc])
            mock_cls.assert_called_once_with(chunk_size=512, chunk_overlap=50)
            instance.get_nodes_from_documents.assert_called_once_with([plain_doc])
        assert nodes == [fake_node]

    def test_custom_chunk_size_passed_to_splitter(self, plain_doc: Document) -> None:
        with patch("backend.rag.indexing.chunking.SentenceSplitter") as mock_cls:
            instance = mock_cls.return_value
            instance.get_nodes_from_documents.return_value = []
            chunk_documents([plain_doc], chunk_size=256, chunk_overlap=10)
            mock_cls.assert_called_once_with(chunk_size=256, chunk_overlap=10)

    def test_mixed_docs_routes_each_correctly(
        self, plain_doc: Document, separated_doc: Document
    ) -> None:
        fake_node = MagicMock()
        with patch("backend.rag.indexing.chunking.SentenceSplitter") as mock_cls:
            instance = mock_cls.return_value
            instance.get_nodes_from_documents.return_value = [fake_node]
            nodes = chunk_documents([plain_doc, separated_doc])
            # SentenceSplitter called once for the plain doc
            mock_cls.assert_called_once()
        # 3 from separated_doc + 1 from plain_doc mock
        assert len(nodes) == 4

    @pytest.mark.parametrize("count", [1, 5, 20])
    def test_all_separated_docs_processed(self, count: int) -> None:
        docs = [Document(text="Post A\n---\nPost B", metadata={}) for _ in range(count)]
        with patch("backend.rag.indexing.chunking.SentenceSplitter") as mock_cls:
            nodes = chunk_documents(docs)
            mock_cls.assert_not_called()
        # Each doc splits into 2 nodes
        assert len(nodes) == count * 2
