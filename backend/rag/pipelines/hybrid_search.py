from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient

from backend.config.settings import settings
from backend.rag.indexing.embedder import get_embedder


class HybridRetrieverPipeline:
    """Retrieval pipeline that combines dense vector search with BM25 (hybrid mode)."""

    def __init__(self, retriever: BaseRetriever) -> None:
        self._retriever = retriever

    @classmethod
    def build(cls, collection_name: str, top_k: int = 5) -> "HybridRetrieverPipeline":
        """Construct a HybridRetrieverPipeline wired to the live Qdrant instance."""
        client = AsyncQdrantClient(
            host=settings.QDRANT_HOST, port=settings.EXTERNAL_QDRANT_PORT
        )
        vector_store = QdrantVectorStore(
            collection_name=collection_name, aclient=client, enable_hybrid=True
        )
        index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=vector_store, embed_model=get_embedder()
        )
        # Configure hybrid retrieval (Dense + BM25)
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            sparse_top_k=top_k,
            vector_store_query_mode="hybrid",
        )
        return cls(retriever=retriever)

    async def retrieve(self, query: str) -> list[NodeWithScore]:
        """Асинхронно виконує гібридний пошук."""
        return await self._retriever.aretrieve(query)
