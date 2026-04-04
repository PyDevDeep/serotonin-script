from pathlib import Path

import httpx
import structlog
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings
from llama_index.embeddings.openai import (  # type: ignore[reportMissingTypeStubs]
    OpenAIEmbedding,
)
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient

from backend.config.settings import settings
from backend.workers.broker import broker

logger = structlog.get_logger()

# Налаштування OpenAI Embedding
_raw_key = settings.OPENAI_API_KEY
openai_key: str = (
    _raw_key.get_secret_value()
    if hasattr(_raw_key, "get_secret_value")
    else str(_raw_key)
)
Settings.embed_model = OpenAIEmbedding(
    model=settings.OPENAI_MODEL_EMBEDDING, api_key=openai_key
)


@broker.task(task_name="ingest_guideline_task", timeout=300)
async def ingest_guideline_task(file_url: str, file_name: str) -> None:
    logger.info("ingest_guideline_started", file_name=file_name)

    try:
        # 1. Завантаження файлу зі Slack
        save_dir = Path("knowledge_base/medical_guidelines")
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / file_name

        slack_token = (
            settings.SLACK_BOT_TOKEN.get_secret_value()
            if hasattr(settings.SLACK_BOT_TOKEN, "get_secret_value")
            else settings.SLACK_BOT_TOKEN
        )

        async with httpx.AsyncClient() as client:
            response = await client.get(
                file_url, headers={"Authorization": f"Bearer {slack_token}"}
            )
            response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(response.content)

        logger.info("file_downloaded_successfully", path=str(file_path))

        # 2. Векторизація через LlamaIndex
        # Використовуємо SimpleDirectoryReader для конкретного файлу
        documents = SimpleDirectoryReader(input_files=[str(file_path)]).load_data()

        # Підключаємось до Qdrant (колекція medical_knowledge)
        qdrant_url = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
        aclient = AsyncQdrantClient(url=qdrant_url)
        vector_store = QdrantVectorStore(
            aclient=aclient, collection_name="medical_knowledge"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # Створюємо індекс і вставляємо документи
        index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=vector_store, storage_context=storage_context
        )
        for doc in documents:
            doc.metadata["source"] = file_name
            await index.ainsert(doc)

        logger.info(
            "guideline_ingestion_success", file_name=file_name, chunks=len(documents)
        )

        # TODO: Додати notify_slack_on_complete для сповіщення користувача про успіх (опціонально)

    except Exception as e:
        logger.error("guideline_ingestion_failed", file_name=file_name, error=str(e))
        raise
