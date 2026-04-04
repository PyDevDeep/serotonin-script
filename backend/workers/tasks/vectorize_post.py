import structlog

from backend.workers.broker import broker

logger = structlog.get_logger()


@broker.task(task_name="vectorize_published_post")
async def vectorize_published_post_task(content: str, platform: str) -> None:
    """
    Фонова задача для векторизації опублікованого посту.
    Додає текст до колекції `doctor_style`, щоб покращувати тон майбутніх генерацій.
    """
    logger.info("vectorization_started", platform=platform)

    try:
        # TODO: Інтегруй сюди свій сервіс LlamaIndex.
        # Тобі потрібно:
        # 1. Зробити Document(text=content, metadata={"platform": platform})
        # 2. Передати його у твій VectorStoreIndex, підключений до колекції `doctor_style`.

        logger.info("vectorization_success", platform=platform)
    except Exception as e:
        logger.error("vectorization_failed", error=str(e), error_type=type(e).__name__)
        raise
