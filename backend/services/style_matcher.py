import re

import structlog

from backend.rag.pipelines.hybrid_search import HybridRetrieverPipeline

logger = structlog.get_logger()


class StyleMatcher:
    def __init__(self) -> None:
        # Використовуємо універсальний гібридний пайплайн замість старого StyleRetriever
        self.retriever = HybridRetrieverPipeline(
            collection_name="doctor_style", top_k=5
        )

    async def get_style_context(self, topic: str) -> str:
        """
        Шукає релевантні тексти лікаря та формує єдиний контекстний рядок.
        """
        logger.info("fetching_style_context", topic=topic)
        nodes = await self.retriever.retrieve(topic)

        if not nodes:
            logger.warning("no_style_context_found", topic=topic)
            return "Стилістичний контекст відсутній."

        context_parts: list[str] = []
        for i, node in enumerate(nodes, 1):
            content = node.get_content()
            # Нормалізуємо пробіли та переноси
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = re.sub(r" +\n", "\n", content)  # пробіли перед \n
            content = re.sub(r"\n +", "\n", content)  # пробіли після \n
            content = re.sub(r"\n{3,}", "\n\n", content)  # 3+ \n → 2
            content = content.strip()
            context_parts.append(f"--- Приклад стилю {i} ---\n{content}")

        return "\n\n".join(context_parts)
