"""
Tests for backend.services.fact_checker.FactChecker.

Coverage:
- Pure/sync helpers: _build_pubmed_queries, _deduplicate, _extract_keywords,
  _has_keyword_overlap, _has_keyword_overlap_en, _merge_web
- Async retrieval paths: _fetch_from_qdrant (Qdrant errors, dedup, sorting)
- _translate_queries: success, malformed JSON fallback, exception fallback
- get_medical_context: all 4 branches (no nodes, relevant nodes pass/fail,
  nodes below threshold), web_context merging
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from backend.services.fact_checker import (
    LOW_RELEVANCE_SIGNAL,
    NO_CONTEXT_SIGNAL,
    RELEVANCE_THRESHOLD,
    FactChecker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    node_id: str,
    score: float,
    content: str = "content",
    metadata: dict[str, str] | None = None,
) -> NodeWithScore:
    """Create a NodeWithScore for testing."""
    node = TextNode(text=content, id_=node_id, metadata=metadata or {})
    return NodeWithScore(node=node, score=score)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retriever() -> AsyncMock:
    """Mock RetrieverProtocol."""
    return AsyncMock()


@pytest.fixture
def mock_pubmed() -> AsyncMock:
    """Mock PubMedClient."""
    return AsyncMock()


@pytest.fixture
def mock_web_scraper() -> AsyncMock:
    """Mock WebScraper."""
    return AsyncMock()


@pytest.fixture
def mock_llm_router() -> AsyncMock:
    """Mock LLMRouter."""
    return AsyncMock()


@pytest.fixture
def checker(
    mock_retriever, mock_pubmed, mock_web_scraper, mock_llm_router
) -> FactChecker:
    """FactChecker instance with all dependencies mocked."""
    return FactChecker(
        retriever=mock_retriever,
        pubmed=mock_pubmed,
        web_scraper=mock_web_scraper,
        llm_router=mock_llm_router,
    )


# ---------------------------------------------------------------------------
# TestBuildPubmedQueries
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildPubmedQueries:
    """_build_pubmed_queries removes Ukrainian stop phrases and trailing punctuation."""

    def test_plain_topic_returned_as_is(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("anxiety treatment")
        assert result == ["anxiety treatment"]

    def test_splits_on_question_mark(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("Anxiety disorders? What to do")
        assert result == ["Anxiety disorders"]

    def test_splits_on_em_dash(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("Тривога—як лікувати")
        assert result == ["Тривога"]

    def test_removes_stop_phrase_найстрашніший(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("найстрашніший симптом депресії")
        assert "найстрашніший" not in result[0]

    def test_removes_stop_phrase_червоні_прапорці(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("червоні прапорці інсульту")
        assert "червоні прапорці" not in result[0]

    def test_strips_trailing_punctuation(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("migraine ,")
        assert not result[0].endswith(",")
        assert not result[0].endswith(" ")

    def test_empty_result_after_cleanup_falls_back_to_original(
        self, checker: FactChecker
    ) -> None:
        # Only the stop phrase, nothing else
        result = checker._build_pubmed_queries("найстрашніший")
        assert result == ["найстрашніший"]

    def test_returns_list(self, checker: FactChecker) -> None:
        result = checker._build_pubmed_queries("depression")
        assert isinstance(result, list)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestDeduplicate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeduplicate:
    """_deduplicate removes nodes with duplicate IDs, preserving first occurrence."""

    def test_no_duplicates_unchanged(self, checker: FactChecker) -> None:
        nodes = [_make_node("a", 0.9), _make_node("b", 0.8)]
        result = checker._deduplicate(nodes)
        assert len(result) == 2

    def test_duplicate_ids_removed(self, checker: FactChecker) -> None:
        nodes = [_make_node("a", 0.9), _make_node("a", 0.5), _make_node("b", 0.8)]
        result = checker._deduplicate(nodes)
        assert len(result) == 2
        ids = [n.node.node_id for n in result]
        assert ids == ["a", "b"]

    def test_empty_list_returns_empty(self, checker: FactChecker) -> None:
        assert checker._deduplicate([]) == []

    def test_all_duplicates_returns_one(self, checker: FactChecker) -> None:
        nodes = [_make_node("x", 0.9), _make_node("x", 0.7), _make_node("x", 0.5)]
        result = checker._deduplicate(nodes)
        assert len(result) == 1
        assert result[0].score == 0.9  # first occurrence kept


# ---------------------------------------------------------------------------
# TestExtractKeywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractKeywords:
    """_extract_keywords filters stop words and short tokens."""

    def test_returns_set(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("anxiety treatment therapy")
        assert isinstance(result, set)

    def test_short_words_excluded(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("the cat sat")
        # "the" is stop word; "cat" and "sat" are 3 chars — below the 4-char minimum
        assert result == set()

    def test_stop_words_excluded_ukrainian(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("це що як депресія")
        assert "це" not in result
        assert "депресія" in result

    def test_stop_words_excluded_english(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("this anxiety treatment")
        assert "this" not in result
        assert "anxiety" in result

    def test_case_insensitive(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("Anxiety TREATMENT")
        assert "anxiety" in result
        assert "treatment" in result

    def test_empty_string_returns_empty_set(self, checker: FactChecker) -> None:
        assert checker._extract_keywords("") == set()

    def test_numbers_excluded(self, checker: FactChecker) -> None:
        result = checker._extract_keywords("1234 anxiety 5678")
        assert "1234" not in result
        assert "anxiety" in result


# ---------------------------------------------------------------------------
# TestHasKeywordOverlap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasKeywordOverlap:
    """_has_keyword_overlap checks topic–content keyword intersection."""

    def test_sufficient_overlap_returns_true(self, checker: FactChecker) -> None:
        topic = "anxiety depression treatment"
        content = "anxiety disorder treatment options and therapy"
        assert checker._has_keyword_overlap(topic, content) is True

    def test_no_overlap_returns_false(self, checker: FactChecker) -> None:
        topic = "cardiac surgery bypass"
        content = "anxiety depression therapy mental health"
        assert checker._has_keyword_overlap(topic, content) is False

    def test_empty_topic_keywords_allows_through(self, checker: FactChecker) -> None:
        # Topic with only stop words → cannot verify → allow through
        assert checker._has_keyword_overlap("the a an", "anything here") is True

    @pytest.mark.parametrize(
        "ratio_desc,topic,content,expected",
        [
            (
                "exactly at threshold",
                "anxiety treatment therapy options",
                "anxiety disorder mental health",
                True,
            ),
            ("below threshold", "cardiac bypass surgery", "anxiety depression", False),
        ],
    )
    def test_threshold_boundary(
        self,
        checker: FactChecker,
        ratio_desc: str,
        topic: str,
        content: str,
        expected: bool,
    ) -> None:
        # TODO: Clarify exact threshold boundary behaviour with developer —
        # KEYWORD_OVERLAP_THRESHOLD is 0.15, parametrize values may shift with word changes
        result = checker._has_keyword_overlap(topic, content)
        assert result == expected


# ---------------------------------------------------------------------------
# TestHasKeywordOverlapEn
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasKeywordOverlapEn:
    """_has_keyword_overlap_en uses PUBMED_KEYWORD_OVERLAP_THRESHOLD (0.5)."""

    def test_high_overlap_returns_true(self, checker: FactChecker) -> None:
        query = "anxiety disorder treatment therapy"
        abstract = "anxiety disorder treatment options with cognitive therapy"
        assert checker._has_keyword_overlap_en(query, abstract) is True

    def test_low_overlap_returns_false(self, checker: FactChecker) -> None:
        query = "anxiety disorder treatment therapy"
        abstract = "cardiac surgery outcomes bypass"
        assert checker._has_keyword_overlap_en(query, abstract) is False

    def test_empty_query_allows_through(self, checker: FactChecker) -> None:
        assert checker._has_keyword_overlap_en("the an a", "anything") is True


# ---------------------------------------------------------------------------
# TestMergeWeb
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeWeb:
    """_merge_web static method combines web_context with rag_context."""

    def test_no_web_context_returns_rag_and_original_status(self) -> None:
        context, status = FactChecker._merge_web(None, "rag content", "ОБМЕЖЕНИЙ")
        assert context == "rag content"
        assert status == "ОБМЕЖЕНИЙ"

    def test_with_web_context_prepends_and_sets_full_status(self) -> None:
        context, status = FactChecker._merge_web(
            "web content", "rag content", "ОБМЕЖЕНИЙ"
        )
        assert context == "web content\n\nrag content"
        assert status == "ПОВНИЙ"

    def test_empty_web_context_string_treated_as_falsy(self) -> None:
        context, status = FactChecker._merge_web("", "rag content", "ОБМЕЖЕНИЙ")
        # empty string is falsy — should behave like no web context
        assert context == "rag content"
        assert status == "ОБМЕЖЕНИЙ"


# ---------------------------------------------------------------------------
# TestFetchFromQdrant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchFromQdrant:
    """_fetch_from_qdrant retrieves, deduplicates, and sorts nodes."""

    @pytest.mark.asyncio
    async def test_returns_sorted_deduplicated_nodes(
        self, checker: FactChecker, mock_retriever: AsyncMock
    ) -> None:
        nodes = [_make_node("b", 0.6), _make_node("a", 0.9), _make_node("a", 0.5)]
        mock_retriever.retrieve.return_value = nodes

        result = await checker._fetch_from_qdrant("depression")
        ids = [n.node.node_id for n in result]
        scores = [n.score for n in result]

        assert "a" not in ids[1:]  # deduped
        assert scores == sorted(scores, key=lambda x: x or 0.0, reverse=True)

    @pytest.mark.asyncio
    async def test_retriever_exception_skipped(
        self, checker: FactChecker, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.side_effect = RuntimeError("Qdrant down")

        result = await checker._fetch_from_qdrant("topic")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(
        self, checker: FactChecker, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever.retrieve.return_value = []
        result = await checker._fetch_from_qdrant("topic")
        assert result == []


# ---------------------------------------------------------------------------
# TestTranslateQueries
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslateQueries:
    """_translate_queries: success, malformed JSON, and generic exception paths."""

    @pytest.mark.asyncio
    async def test_success_returns_translated_list(
        self, checker: FactChecker, mock_llm_router: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.message.content = '["anxiety treatment", "depression therapy"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        result = await checker._translate_queries(["тривога лікування"])
        assert result == ["anxiety treatment", "depression therapy"]

    @pytest.mark.asyncio
    async def test_success_with_markdown_code_block(
        self, checker: FactChecker, mock_llm_router: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.message.content = '```json\n["anxiety"]\n```'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        result = await checker._translate_queries(["тривога"])
        assert result == ["anxiety"]

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_to_original(
        self, checker: FactChecker, mock_llm_router: AsyncMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.message.content = "not valid json"
        mock_llm_router.achat_with_fallback.return_value = mock_response

        original = ["тривога лікування"]
        result = await checker._translate_queries(original)
        assert result == original

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_original(
        self, checker: FactChecker, mock_llm_router: AsyncMock
    ) -> None:
        mock_llm_router.achat_with_fallback.side_effect = RuntimeError(
            "LLM unavailable"
        )

        original = ["стрес"]
        result = await checker._translate_queries(original)
        assert result == original


# ---------------------------------------------------------------------------
# TestGetMedicalContext
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMedicalContext:
    """get_medical_context orchestration — all branching scenarios."""

    @pytest.mark.asyncio
    async def test_no_qdrant_nodes_pubmed_returns_content(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_pubmed: AsyncMock,
        mock_web_scraper: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Branch 1: Qdrant empty → PubMed hit → ПОВНИЙ status."""
        mock_retriever.retrieve.return_value = []
        mock_pubmed.search_and_fetch.return_value = [
            {
                "uid": "1",
                "title": "Anxiety Study",
                "abstract": "anxiety treatment results",
                "url": "http://pubmed/1",
            }
        ]
        mock_web_scraper.scrape.return_value = None

        # Ensure translation returns english query
        mock_response = MagicMock()
        mock_response.message.content = '["anxiety treatment"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        context, status = await checker.get_medical_context("тривога лікування")
        assert status == "ПОВНИЙ"
        assert "PubMed" in context

    @pytest.mark.asyncio
    async def test_no_qdrant_nodes_pubmed_empty_returns_no_context_signal(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_pubmed: AsyncMock,
        mock_web_scraper: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Branch 1: Qdrant empty → PubMed empty → NO_CONTEXT_SIGNAL."""
        mock_retriever.retrieve.return_value = []
        mock_pubmed.search_and_fetch.return_value = []
        mock_web_scraper.scrape.return_value = None

        mock_response = MagicMock()
        mock_response.message.content = '["anxiety"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        context, status = await checker.get_medical_context("тривога")
        assert status == "ВІДСУТНІЙ"
        assert context == NO_CONTEXT_SIGNAL

    @pytest.mark.asyncio
    async def test_relevant_nodes_pass_keyword_overlap_returns_full(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_web_scraper: AsyncMock,
    ) -> None:
        """Branch 2: relevant nodes present AND pass keyword overlap → ПОВНИЙ."""
        topic = "anxiety treatment therapy options"
        content = "anxiety treatment therapy options mental health"
        node = _make_node(
            "n1", 0.85, content=content, metadata={"file_name": "study.pdf"}
        )

        mock_retriever.retrieve.return_value = [node]
        mock_web_scraper.scrape.return_value = None

        context, status = await checker.get_medical_context(topic)
        assert status == "ПОВНИЙ"
        assert "study.pdf" in context

    @pytest.mark.asyncio
    async def test_nodes_below_relevance_threshold_fallback_pubmed(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_pubmed: AsyncMock,
        mock_web_scraper: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Branch 3: nodes exist but all below RELEVANCE_THRESHOLD → PubMed fallback."""
        node = _make_node("n1", RELEVANCE_THRESHOLD - 0.1, content="some content")
        mock_retriever.retrieve.return_value = [node]
        mock_pubmed.search_and_fetch.return_value = []
        mock_web_scraper.scrape.return_value = None

        mock_response = MagicMock()
        mock_response.message.content = '["anxiety"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        context, status = await checker.get_medical_context("anxiety")
        assert status == "ОБМЕЖЕНИЙ"
        assert context == LOW_RELEVANCE_SIGNAL

    @pytest.mark.asyncio
    async def test_web_context_merged_and_status_overridden_to_full(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_pubmed: AsyncMock,
        mock_web_scraper: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Web source always overrides status to ПОВНИЙ."""
        mock_retriever.retrieve.return_value = []
        mock_pubmed.search_and_fetch.return_value = []
        mock_web_scraper.scrape.return_value = "scraped web content"

        mock_response = MagicMock()
        mock_response.message.content = '["anxiety"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        context, status = await checker.get_medical_context(
            "anxiety", source_url="https://example.com"
        )
        assert status == "ПОВНИЙ"
        assert "scraped web content" in context

    @pytest.mark.asyncio
    async def test_relevant_nodes_all_fail_keyword_overlap_fallback_pubmed(
        self,
        checker: FactChecker,
        mock_retriever: AsyncMock,
        mock_pubmed: AsyncMock,
        mock_web_scraper: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Relevant nodes exist but none pass keyword overlap → PubMed fallback."""
        topic = "cardiac bypass surgery"
        # Node content has zero overlap with topic
        node = _make_node(
            "n1", 0.9, content="mental health anxiety depression therapy options"
        )
        mock_retriever.retrieve.return_value = [node]
        mock_pubmed.search_and_fetch.return_value = []
        mock_web_scraper.scrape.return_value = None

        mock_response = MagicMock()
        mock_response.message.content = '["cardiac bypass"]'
        mock_llm_router.achat_with_fallback.return_value = mock_response

        _, status = await checker.get_medical_context(topic)
        assert status == "ОБМЕЖЕНИЙ"


# ---------------------------------------------------------------------------
# TestFetchFromPubmed — branch coverage for _fetch_from_pubmed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchFromPubmed:
    """_fetch_from_pubmed internal branches not reachable via get_medical_context mocks."""

    @pytest.mark.asyncio
    async def test_pubmed_query_exception_skipped(
        self,
        checker: FactChecker,
        mock_pubmed: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Lines 235-236: PubMed search raises — exception is logged and skipped, returns None."""
        mock_pubmed.search_and_fetch.side_effect = RuntimeError("PubMed 503")
        mock_llm_router.achat_with_fallback.return_value = MagicMock(
            message=MagicMock(content='["anxiety"]')
        )
        result = await checker._fetch_from_pubmed("anxiety")
        assert result is None

    @pytest.mark.asyncio
    async def test_all_articles_rejected_by_keyword_overlap_returns_none(
        self,
        checker: FactChecker,
        mock_pubmed: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Lines 256-261, 268-269: articles found but none pass keyword overlap → None."""
        mock_llm_router.achat_with_fallback.return_value = MagicMock(
            message=MagicMock(content='["cardiac bypass surgery"]')
        )
        # Article content has zero overlap with "cardiac bypass surgery"
        mock_pubmed.search_and_fetch.return_value = [
            {
                "uid": "1",
                "title": "Mental health anxiety depression",
                "abstract": "anxiety depression therapy mental health treatment",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1",
            }
        ]
        result = await checker._fetch_from_pubmed("cardiac bypass surgery")
        assert result is None

    @pytest.mark.asyncio
    async def test_duplicate_pubmed_articles_deduplicated(
        self,
        checker: FactChecker,
        mock_pubmed: AsyncMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Same uid returned from two queries → only one entry in context."""
        mock_llm_router.achat_with_fallback.return_value = MagicMock(
            message=MagicMock(content='["anxiety treatment", "anxiety therapy"]')
        )
        article = {
            "uid": "42",
            "title": "Anxiety treatment review therapy",
            "abstract": "anxiety treatment therapy review clinical results",
            "url": "https://pubmed.ncbi.nlm.nih.gov/42",
        }
        mock_pubmed.search_and_fetch.return_value = [article]
        result = await checker._fetch_from_pubmed("anxiety treatment therapy")
        assert result is not None
        # Appears exactly once despite two queries returning the same uid
        assert result.count("uid=42") == 0  # uid not in output, but title appears once
        assert result.count("Anxiety treatment review") == 1
