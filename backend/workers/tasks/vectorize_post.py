from pathlib import Path

import structlog
from llama_index.core import Document, StorageContext, VectorStoreIndex
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

# Safely extract the token from Pydantic SecretStr
_raw_key = settings.OPENAI_API_KEY
openai_key: str = (
    _raw_key.get_secret_value()
    if hasattr(_raw_key, "get_secret_value")
    else str(_raw_key)
)

# Configure the global embedding model for vectorization
embed_model = OpenAIEmbedding(
    model=settings.OPENAI_MODEL_EMBEDDING, dimensions=768, api_key=openai_key
)
Settings.embed_model = embed_model


@broker.task(task_name="vectorize_published_post")
async def vectorize_published_post_task(content: str, platform: str) -> None:
    """
    Векторизує опублікований пост через OpenAI та зберігає його у Qdrant.
    """
    logger.info("vectorization_started", platform=platform)

    try:
        # --- 1. Save to Markdown (backup copy) ---
        md_file_path = Path("knowledge_base/doctor_style/posts/doctor_style_posts.md")
        md_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Append the post with a separator
        with md_file_path.open("a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{content.strip()}")

        logger.info("markdown_backup_success", file_path=str(md_file_path))

        # --- 2. Vectorize and store in Qdrant ---
        qdrant_url = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
        aclient = AsyncQdrantClient(url=qdrant_url)

        vector_store = QdrantVectorStore(
            aclient=aclient, collection_name="doctor_style"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        doc = Document(
            text=content,
            metadata={
                "platform": platform,
                "source": "n8n_feedback_loop",
                "type": "published_post",
            },
        )

        index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=vector_store, storage_context=storage_context
        )

        await index.ainsert(doc)

        logger.info("vectorization_success", platform=platform)
    except Exception as e:
        logger.error("vectorization_failed", error=str(e), error_type=type(e).__name__)
        raise
