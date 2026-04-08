"""
Tests for KnowledgeRetriever, StyleRetriever, and HybridRetrieverPipeline.

Після DI-рефактору кожен клас приймає BaseRetriever через конструктор.
Тести не потребують жодного patch — mock зводиться до одного рядка.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore

from backend.rag.pipelines.hybrid_search import HybridRetrieverPipeline
from backend.rag.retrieval.base import RetrieverProtocol
from backend.rag.retrieval.knowledge_retriever import KnowledgeRetriever
from backend.rag.retrieval.style_retriever import StyleRetriever

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_retriever() -> MagicMock:
    """BaseRetriever mock з async aretrieve()."""
    mock = MagicMock(spec=BaseRetriever)
    mock.aretrieve = AsyncMock()
    return mock


def make_node(text: str = "chunk", score: float = 0.9) -> MagicMock:
    node = MagicMock()
    node.score = score
    node.node.text = text
    return node


# ---------------------------------------------------------------------------
# RetrieverProtocol conformance
# ---------------------------------------------------------------------------


class TestRetrieverProtocol:
    def test_knowledge_retriever_satisfies_protocol(self) -> None:
        kr = KnowledgeRetriever(retriever=make_mock_retriever())
        assert isinstance(kr, RetrieverProtocol)

    def test_style_retriever_satisfies_protocol(self) -> None:
        sr = StyleRetriever(retriever=make_mock_retriever())
        assert isinstance(sr, RetrieverProtocol)

    def test_hybrid_pipeline_satisfies_protocol(self) -> None:
        hp = HybridRetrieverPipeline(retriever=make_mock_retriever())
        assert isinstance(hp, RetrieverProtocol)

    def test_plain_async_mock_satisfies_protocol(self) -> None:
        """Будь-який об'єкт з async retrieve() задовольняє Protocol."""

        class FakeRetriever:
            async def retrieve(self, query: str) -> list[NodeWithScore]:
                return []

        assert isinstance(FakeRetriever(), RetrieverProtocol)


# ---------------------------------------------------------------------------
# KnowledgeRetriever
# ---------------------------------------------------------------------------


class TestKnowledgeRetriever:
    @pytest.fixture
    def mock_inner(self) -> MagicMock:
        return make_mock_retriever()

    @pytest.fixture
    def retriever(self, mock_inner: MagicMock) -> KnowledgeRetriever:
        return KnowledgeRetriever(retriever=mock_inner)

    @pytest.mark.asyncio
    async def test_retrieve_delegates_to_inner_retriever(
        self, retriever: KnowledgeRetriever, mock_inner: MagicMock
    ) -> None:
        expected = [make_node("medical fact")]
        mock_inner.aretrieve.return_value = expected

        result = await retriever.retrieve("serotonin and depression")

        mock_inner.aretrieve.assert_awaited_once_with("serotonin and depression")
        assert result == expected

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_list(
        self, retriever: KnowledgeRetriever, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.return_value = []
        result = await retriever.retrieve("unknown topic")
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_propagates_exception(
        self, retriever: KnowledgeRetriever, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.side_effect = RuntimeError("Qdrant unavailable")
        with pytest.raises(RuntimeError, match="Qdrant unavailable"):
            await retriever.retrieve("query")

    @pytest.mark.asyncio
    async def test_retrieve_passes_empty_query(
        self, retriever: KnowledgeRetriever, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.return_value = []
        await retriever.retrieve("")
        mock_inner.aretrieve.assert_awaited_once_with("")

    def test_build_classmethod_exists(self) -> None:
        assert callable(KnowledgeRetriever.build)

    def test_build_wires_medical_knowledge_collection(self) -> None:
        with (
            patch("backend.rag.retrieval.knowledge_retriever.AsyncQdrantClient"),
            patch(
                "backend.rag.retrieval.knowledge_retriever.QdrantVectorStore"
            ) as p_store,
            patch(
                "backend.rag.retrieval.knowledge_retriever.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.retrieval.knowledge_retriever.get_embedder"),
        ):
            p_idx.return_value.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            KnowledgeRetriever.build()
            assert p_store.call_args.kwargs["collection_name"] == "medical_knowledge"

    def test_build_sets_top_k_3(self) -> None:
        with (
            patch("backend.rag.retrieval.knowledge_retriever.AsyncQdrantClient"),
            patch("backend.rag.retrieval.knowledge_retriever.QdrantVectorStore"),
            patch(
                "backend.rag.retrieval.knowledge_retriever.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.retrieval.knowledge_retriever.get_embedder"),
        ):
            mock_index = MagicMock()
            mock_index.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            p_idx.return_value = mock_index
            KnowledgeRetriever.build()
            mock_index.as_retriever.assert_called_once_with(similarity_top_k=3)


# ---------------------------------------------------------------------------
# StyleRetriever
# ---------------------------------------------------------------------------


class TestStyleRetriever:
    @pytest.fixture
    def mock_inner(self) -> MagicMock:
        return make_mock_retriever()

    @pytest.fixture
    def retriever(self, mock_inner: MagicMock) -> StyleRetriever:
        return StyleRetriever(retriever=mock_inner)

    @pytest.mark.asyncio
    async def test_retrieve_delegates_to_inner_retriever(
        self, retriever: StyleRetriever, mock_inner: MagicMock
    ) -> None:
        expected = [make_node("style sample", 0.88)]
        mock_inner.aretrieve.return_value = expected

        result = await retriever.retrieve("warm empathetic tone")

        mock_inner.aretrieve.assert_awaited_once_with("warm empathetic tone")
        assert result == expected

    @pytest.mark.asyncio
    async def test_retrieve_returns_multiple_nodes(
        self, retriever: StyleRetriever, mock_inner: MagicMock
    ) -> None:
        nodes = [make_node(f"style {i}") for i in range(5)]
        mock_inner.aretrieve.return_value = nodes
        result = await retriever.retrieve("clinical tone")
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_retrieve_propagates_exception(
        self, retriever: StyleRetriever, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.side_effect = ConnectionError("network error")
        with pytest.raises(ConnectionError):
            await retriever.retrieve("query")

    def test_build_wires_doctor_style_collection(self) -> None:
        with (
            patch("backend.rag.retrieval.style_retriever.AsyncQdrantClient"),
            patch("backend.rag.retrieval.style_retriever.QdrantVectorStore") as p_store,
            patch(
                "backend.rag.retrieval.style_retriever.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.retrieval.style_retriever.get_embedder"),
        ):
            p_idx.return_value.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            StyleRetriever.build()
            assert p_store.call_args.kwargs["collection_name"] == "doctor_style"

    def test_build_sets_top_k_5(self) -> None:
        with (
            patch("backend.rag.retrieval.style_retriever.AsyncQdrantClient"),
            patch("backend.rag.retrieval.style_retriever.QdrantVectorStore"),
            patch(
                "backend.rag.retrieval.style_retriever.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.retrieval.style_retriever.get_embedder"),
        ):
            mock_index = MagicMock()
            mock_index.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            p_idx.return_value = mock_index
            StyleRetriever.build()
            mock_index.as_retriever.assert_called_once_with(similarity_top_k=5)


# ---------------------------------------------------------------------------
# HybridRetrieverPipeline
# ---------------------------------------------------------------------------


class TestHybridRetrieverPipeline:
    @pytest.fixture
    def mock_inner(self) -> MagicMock:
        return make_mock_retriever()

    @pytest.fixture
    def pipeline(self, mock_inner: MagicMock) -> HybridRetrieverPipeline:
        return HybridRetrieverPipeline(retriever=mock_inner)

    @pytest.mark.asyncio
    async def test_retrieve_delegates_to_inner_retriever(
        self, pipeline: HybridRetrieverPipeline, mock_inner: MagicMock
    ) -> None:
        expected = [make_node("hybrid result")]
        mock_inner.aretrieve.return_value = expected

        result = await pipeline.retrieve("vitamin D deficiency")

        mock_inner.aretrieve.assert_awaited_once_with("vitamin D deficiency")
        assert result == expected

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_list(
        self, pipeline: HybridRetrieverPipeline, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.return_value = []
        result = await pipeline.retrieve("obscure topic")
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_propagates_exception(
        self, pipeline: HybridRetrieverPipeline, mock_inner: MagicMock
    ) -> None:
        mock_inner.aretrieve.side_effect = TimeoutError("timeout")
        with pytest.raises(TimeoutError):
            await pipeline.retrieve("query")

    def test_build_enables_hybrid_mode(self) -> None:
        with (
            patch("backend.rag.pipelines.hybrid_search.AsyncQdrantClient"),
            patch("backend.rag.pipelines.hybrid_search.QdrantVectorStore") as p_store,
            patch(
                "backend.rag.pipelines.hybrid_search.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.pipelines.hybrid_search.get_embedder"),
        ):
            p_idx.return_value.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            HybridRetrieverPipeline.build(collection_name="test_col", top_k=3)
            assert p_store.call_args.kwargs["enable_hybrid"] is True

    def test_build_passes_collection_name(self) -> None:
        with (
            patch("backend.rag.pipelines.hybrid_search.AsyncQdrantClient"),
            patch("backend.rag.pipelines.hybrid_search.QdrantVectorStore") as p_store,
            patch(
                "backend.rag.pipelines.hybrid_search.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.pipelines.hybrid_search.get_embedder"),
        ):
            p_idx.return_value.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            HybridRetrieverPipeline.build(collection_name="doctor_style", top_k=5)
            assert p_store.call_args.kwargs["collection_name"] == "doctor_style"

    def test_build_passes_top_k_to_retriever(self) -> None:
        with (
            patch("backend.rag.pipelines.hybrid_search.AsyncQdrantClient"),
            patch("backend.rag.pipelines.hybrid_search.QdrantVectorStore"),
            patch(
                "backend.rag.pipelines.hybrid_search.VectorStoreIndex.from_vector_store"
            ) as p_idx,
            patch("backend.rag.pipelines.hybrid_search.get_embedder"),
        ):
            mock_index = MagicMock()
            mock_index.as_retriever.return_value = MagicMock(spec=BaseRetriever)
            p_idx.return_value = mock_index
            HybridRetrieverPipeline.build(collection_name="col", top_k=7)
            mock_index.as_retriever.assert_called_once_with(
                similarity_top_k=7,
                sparse_top_k=7,
                vector_store_query_mode="hybrid",
            )
