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

# Витягуємо токен безпечно (Pydantic SecretStr)
_raw_key = settings.OPENAI_API_KEY
openai_key: str = (
    _raw_key.get_secret_value()
    if hasattr(_raw_key, "get_secret_value")
    else str(_raw_key)
)

# Налаштовуємо глобальну модель для векторизації
embed_model = OpenAIEmbedding(model=settings.OPENAI_MODEL_EMBEDDING, api_key=openai_key)
Settings.embed_model = embed_model


@broker.task(task_name="vectorize_published_post")
async def vectorize_published_post_task(content: str, platform: str) -> None:
    """
    Векторизує опублікований пост через OpenAI та зберігає його у Qdrant.
    """
    logger.info("vectorization_started", platform=platform)

    try:
        # 1. Підключаємось до Qdrant
        qdrant_url = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
        aclient = AsyncQdrantClient(url=qdrant_url)

        # Передаємо AsyncQdrantClient в параметр aclient
        vector_store = QdrantVectorStore(
            aclient=aclient, collection_name="doctor_style"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 2. Створюємо документ із метаданими
        doc = Document(
            text=content,
            metadata={
                "platform": platform,
                "source": "n8n_feedback_loop",
                "type": "published_post",
            },
        )

        # 3. Векторизуємо та зберігаємо у БД асинхронно
        # Якщо колекції немає, QdrantVectorStore створит її під капотом
        # коли ми будемо використовувати aclient

        # Створюємо порожній індекс, прив'язаний до Qdrant
        index = VectorStoreIndex.from_vector_store(  # type: ignore[reportUnknownMemberType]
            vector_store=vector_store, storage_context=storage_context
        )

        # Вставляємо документ асинхронно
        await index.ainsert(doc)

        logger.info("vectorization_success", platform=platform)
    except Exception as e:
        logger.error("vectorization_failed", error=str(e), error_type=type(e).__name__)
        raise
