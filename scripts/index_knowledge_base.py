import asyncio
import os
from pathlib import Path

import structlog
from dotenv import load_dotenv
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings
from llama_index.vector_stores.qdrant import (  # type: ignore[reportMissingTypeStubs]
    QdrantVectorStore,
)
from qdrant_client import AsyncQdrantClient, QdrantClient

from backend.rag.indexing.chunking import chunk_documents
from backend.rag.indexing.document_loader import load_documents_from_dir
from backend.rag.indexing.embedder import get_embedder

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


async def index_collection(collection_name: str, data_dir: str):
    logger.info("indexing_started", collection=collection_name, directory=data_dir)

    if not Path(data_dir).exists():
        logger.warning("directory_not_found_skipping", directory=data_dir)
        return

    # 1. Завантаження
    documents = load_documents_from_dir(data_dir)
    if not documents:
        logger.warning("no_documents_found", directory=data_dir)
        return

    # 2. Чанкінг
    nodes = chunk_documents(documents)
    logger.info(
        "chunking_completed", chunks_count=len(nodes), documents_count=len(documents)
    )

    # 3. Підключення до Qdrant (локальний тунель/хост)
    qdrant_port = int(os.environ.get("EXTERNAL_QDRANT_PORT", 6333))
    client = AsyncQdrantClient(host="127.0.0.1", port=qdrant_port)
    sync_client = QdrantClient(host="127.0.0.1", port=qdrant_port)

    vector_store = QdrantVectorStore(
        collection_name=collection_name,
        client=sync_client,
        aclient=client,
        enable_hybrid=True,
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # 4. Налаштування глобальних налаштувань LlamaIndex
    Settings.embed_model = get_embedder()
    Settings.llm = None  # Вимикаємо LLM під час індексації, щоб не витрачати токени

    # 5. Генерація векторів та індексація
    # 5. Генерація векторів та індексація
    logger.info("generating_embeddings_and_saving_to_qdrant")
    VectorStoreIndex(nodes=nodes, storage_context=storage_context, show_progress=True)
    logger.info("indexing_completed_successfully", collection=collection_name)


async def main():
    kb_path = Path("knowledge_base")

    await index_collection(
        collection_name="doctor_style", data_dir=str(kb_path / "doctor_style")
    )

    await index_collection(
        collection_name="medical_knowledge",
        data_dir=str(kb_path / "medical_guidelines"),
    )


if __name__ == "__main__":
    asyncio.run(main())
