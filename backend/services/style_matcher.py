import re

import structlog

from backend.rag.retrieval.base import RetrieverProtocol

logger = structlog.get_logger()


class StyleMatcher:
    """Retrieves doctor-style examples from Qdrant and formats them as a context string."""

    def __init__(self, retriever: RetrieverProtocol) -> None:
        self.retriever = retriever

    async def get_style_context(self, topic: str) -> str:
        """Retrieve relevant doctor-style texts and return them as a single context string."""
        logger.info("fetching_style_context", topic=topic)
        nodes = await self.retriever.retrieve(topic)

        if not nodes:
            logger.warning("no_style_context_found", topic=topic)
            return "No style context found."

        context_parts: list[str] = []
        for i, node in enumerate(nodes, 1):
            content = node.get_content()
            # Normalize whitespace and line breaks
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = re.sub(r" +\n", "\n", content)  # trailing spaces before \n
            content = re.sub(r"\n +", "\n", content)  # leading spaces after \n
            content = re.sub(r"\n{3,}", "\n\n", content)  # collapse 3+ newlines to 2
            content = content.strip()
            context_parts.append(f"--- Приклад стилю {i} ---\n{content}")

        return "\n\n".join(context_parts)
