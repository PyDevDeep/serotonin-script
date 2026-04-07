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
from backend.workers.callbacks import (
    notify_slack_upload_failure,
    notify_slack_upload_success,
)

logger = structlog.get_logger()

# Configure the OpenAI embedding model
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
async def ingest_guideline_task(
    file_url: str, file_name: str, user_id: str | None = None
) -> None:
    """Download a file from Slack, vectorize it, and store it in Qdrant."""
    logger.info("ingest_guideline_started", file_name=file_name)

    try:
        # 1. Download the file from Slack
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

        # 2. Vectorize with LlamaIndex using SimpleDirectoryReader for the specific file
        documents = SimpleDirectoryReader(input_files=[str(file_path)]).load_data()

        # Connect to Qdrant (medical_knowledge collection)
        qdrant_url = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
        aclient = AsyncQdrantClient(url=qdrant_url)
        vector_store = QdrantVectorStore(
            aclient=aclient, collection_name="medical_knowledge"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # Build the index and insert documents
        index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=vector_store, storage_context=storage_context
        )
        for doc in documents:
            doc.metadata["source"] = file_name
            await index.ainsert(doc)

        logger.info(
            "guideline_ingestion_success", file_name=file_name, chunks=len(documents)
        )

        # Notify on success
        if user_id:
            await notify_slack_upload_success(user_id=user_id, file_name=file_name)

    except Exception as e:
        logger.error("guideline_ingestion_failed", file_name=file_name, error=str(e))

        # Notify on failure
        if user_id:
            await notify_slack_upload_failure(
                user_id=user_id, file_name=file_name, error_msg=str(e)
            )
        raise
