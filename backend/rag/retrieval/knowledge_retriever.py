from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient

from backend.config.settings import settings
from backend.rag.indexing.embedder import get_embedder


class KnowledgeRetriever:
    """Retrieves medical knowledge chunks from the Qdrant vector store."""

    def __init__(self) -> None:
        """Initialise the Qdrant client, vector store, index, and retriever."""
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST, port=settings.EXTERNAL_QDRANT_PORT
        )
        self.vector_store = QdrantVectorStore(
            collection_name="medical_knowledge", aclient=self.client
        )
        self.index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=self.vector_store, embed_model=get_embedder()
        )
        # Returns top-3 guidelines per Acceptance Criteria
        self.retriever = self.index.as_retriever(similarity_top_k=3)

    async def retrieve(self, query: str) -> list[NodeWithScore]:
        """Асинхронно виконує пошук медичних фактів за запитом."""
        return await self.retriever.aretrieve(query)
