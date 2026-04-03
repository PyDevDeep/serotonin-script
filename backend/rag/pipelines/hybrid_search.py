from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient

from backend.config.settings import settings
from backend.rag.indexing.embedder import get_embedder


class HybridRetrieverPipeline:
    def __init__(self, collection_name: str, top_k: int = 5) -> None:
        self.client = AsyncQdrantClient(
            host="127.0.0.1", port=settings.EXTERNAL_QDRANT_PORT
        )
        self.vector_store = QdrantVectorStore(
            collection_name=collection_name, aclient=self.client, enable_hybrid=True
        )
        self.index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=self.vector_store, embed_model=get_embedder()
        )

        # Налаштовуємо гібридний запит (Dense + BM25)
        self.retriever = self.index.as_retriever(
            similarity_top_k=top_k, sparse_top_k=top_k, vector_store_query_mode="hybrid"
        )

    async def retrieve(self, query: str) -> list[NodeWithScore]:
        """Асинхронно виконує гібридний пошук."""
        return await self.retriever.aretrieve(query)
