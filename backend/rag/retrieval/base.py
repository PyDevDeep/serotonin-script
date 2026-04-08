"""Shared retriever contract for all RAG retrieval implementations."""

from typing import Protocol, runtime_checkable

from llama_index.core.schema import NodeWithScore


@runtime_checkable
class RetrieverProtocol(Protocol):
    """Anything that can retrieve NodeWithScore items for a text query."""

    async def retrieve(self, query: str) -> list[NodeWithScore]:
        """Return ranked nodes relevant to query."""
        ...
