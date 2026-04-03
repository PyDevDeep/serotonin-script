from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient

from backend.config.settings import settings
from backend.rag.indexing.embedder import get_embedder


class StyleRetriever:
    def __init__(self) -> None:
        # Підключення до прокинутого порту для локальної розробки (uvicorn)
        self.client = AsyncQdrantClient(
            host="127.0.0.1", port=settings.EXTERNAL_QDRANT_PORT
        )
        self.vector_store = QdrantVectorStore(
            collection_name="doctor_style", aclient=self.client
        )
        self.index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=self.vector_store, embed_model=get_embedder()
        )
        # Згідно з Acceptance Criteria: повертає топ-5 релевантних текстів
        self.retriever = self.index.as_retriever(similarity_top_k=5)

    async def retrieve(self, query: str) -> list[NodeWithScore]:
        """Асинхронно виконує пошук стилістичних фрагментів за запитом."""
        return await self.retriever.aretrieve(query)
