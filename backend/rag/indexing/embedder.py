from llama_index.embeddings.openai import (  # type: ignore[reportMissingTypeStubs]
    OpenAIEmbedding,
)

from backend.config.settings import settings


def get_embedder() -> OpenAIEmbedding:
    """
    Ініціалізує та повертає модель ембедингів OpenAI (text-embedding-3-small).
    Розмірність жорстко задана 768, щоб відповідати конфігурації Qdrant колекцій.
    """
    return OpenAIEmbedding(
        model=settings.OPENAI_MODEL_EMBEDDING,
        dimensions=768,
        api_key=settings.OPENAI_API_KEY.get_secret_value(),
    )
