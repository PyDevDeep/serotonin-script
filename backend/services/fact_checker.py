import asyncio
import re

import structlog
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.schema import NodeWithScore

from backend.agents.prompts.system_prompts import PUBMED_TRANSLATION_PROMPT
from backend.integrations.external.pubmed_client import PubMedClient
from backend.integrations.external.web_scraper import WebScraper
from backend.integrations.llm.router import LLMRouter
from backend.models.schemas import PubMedArticle
from backend.rag.retrieval.base import RetrieverProtocol

logger = structlog.get_logger()

RELEVANCE_THRESHOLD = 0.7
KEYWORD_OVERLAP_THRESHOLD = 0.15
PUBMED_KEYWORD_OVERLAP_THRESHOLD = 0.5
LOW_RELEVANCE_SIGNAL = "[LIMITED CONTEXT]: Found materials are only partially relevant. Use only general recommendations without clinical claims about specific drugs."
NO_CONTEXT_SIGNAL = (
    "[NO CONTEXT]: No materials found for this topic. Do not generate clinical claims."
)


class FactChecker:
    """Gathers and filters medical context from Qdrant, PubMed, and web sources."""

    def __init__(
        self,
        retriever: RetrieverProtocol,
        pubmed: PubMedClient,
        web_scraper: WebScraper,
        llm_router: LLMRouter,
    ) -> None:
        self.retriever = retriever
        self.pubmed = pubmed
        self.web_scraper = web_scraper
        self.llm_router = llm_router

    def _build_queries(self, topic: str) -> list[str]:
        """Return the topic as-is for use as a Qdrant query."""
        return [topic]

    def _build_pubmed_queries(self, topic: str) -> list[str]:
        """Build a cleaned PubMed-friendly query string from the topic."""
        clean = re.split(r"[?—]", topic)[0].strip()  # take only the first segment

        stop_phrases = [
            r"найстрашніший",
            r"червоні прапорці",
            r"які мають насторожити",
            r"міф чи справді",
            r"де зв.язок",
            r"ключ до",
        ]
        for phrase in stop_phrases:
            clean = re.sub(phrase, "", clean, flags=re.IGNORECASE).strip()

        clean = re.sub(
            r"[\s\-:,]+$", "", clean
        ).strip()  # strip trailing punctuation after cleanup

        return [clean] if clean else [topic]

    def _deduplicate(self, nodes: list[NodeWithScore]) -> list[NodeWithScore]:
        """Return nodes with duplicate node IDs removed."""
        seen: set[str] = set()
        result: list[NodeWithScore] = []
        for node in nodes:
            node_id = node.node.node_id
            if node_id not in seen:
                seen.add(node_id)
                result.append(node)
        return result

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful words from text, filtering out stop words."""
        stop_words = {
            "це",
            "що",
            "як",
            "але",
            "або",
            "та",
            "чи",
            "від",
            "до",
            "на",
            "за",
            "по",
            "при",
            "для",
            "про",
            "між",
            "під",
            "над",
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "that",
            "this",
            "which",
            "their",
            "they",
            "from",
            "by",
            "not",
        }
        words = re.findall(r"\b[a-zA-Zа-яА-ЯіІїЇєЄ]{4,}\b", text.lower())
        return {w for w in words if w not in stop_words}

    def _has_keyword_overlap(self, topic: str, content: str) -> bool:
        """Return True if the keyword overlap between topic and chunk text meets the threshold."""
        topic_keywords = self._extract_keywords(topic)
        if not topic_keywords:
            return True  # cannot verify — allow through

        content_keywords = self._extract_keywords(content)
        overlap = topic_keywords & content_keywords
        overlap_ratio = len(overlap) / len(topic_keywords)

        logger.debug(
            "keyword_overlap_check",
            topic_keywords=list(topic_keywords),
            overlap=list(overlap),
            ratio=round(overlap_ratio, 3),
        )
        return overlap_ratio >= KEYWORD_OVERLAP_THRESHOLD

    async def _fetch_from_qdrant(self, topic: str) -> list[NodeWithScore]:
        """Retrieve deduplicated nodes from Qdrant for all topic queries."""
        queries = self._build_queries(topic)
        logger.info("medical_queries_built", queries=queries)

        results = await asyncio.gather(
            *[self.retriever.retrieve(q) for q in queries],
            return_exceptions=True,
        )

        all_nodes: list[NodeWithScore] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "medical_query_failed",
                    query=queries[i],
                    error=str(result),
                )
                continue
            all_nodes.extend(result)

        unique = self._deduplicate(all_nodes)
        unique.sort(key=lambda n: n.score or 0.0, reverse=True)
        return unique

    async def _translate_queries(self, queries: list[str]) -> list[str]:
        """Translate Ukrainian sub-queries to English for PubMed via the LLMRouter."""
        import json

        prompt = PUBMED_TRANSLATION_PROMPT.format(queries=queries)
        message = ChatMessage(role=MessageRole.USER, content=prompt)

        try:
            response = await self.llm_router.achat_with_fallback(
                primary_messages=[message],
                fallback_messages=[message],
            )
            text = response.message.content or ""
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            translated: list[str] = json.loads(cleaned)
            logger.info(
                "pubmed_queries_translated", original=queries, translated=translated
            )
            return translated
        except (json.JSONDecodeError, IndexError, KeyError, Exception) as e:
            logger.warning("pubmed_translation_failed", error=str(e), fallback=queries)
            return queries

    def _has_keyword_overlap_en(self, translated_query: str, content: str) -> bool:
        """Return True if keyword overlap between an English query and an English abstract meets the threshold."""
        query_keywords = self._extract_keywords(translated_query)
        if not query_keywords:
            return True  # cannot verify — allow through

        content_keywords = self._extract_keywords(content)
        overlap = query_keywords & content_keywords
        overlap_ratio = len(overlap) / len(query_keywords)

        logger.debug(
            "keyword_overlap_check_en",
            query_keywords=list(query_keywords),
            overlap=list(overlap),
            ratio=round(overlap_ratio, 3),
        )
        return overlap_ratio >= PUBMED_KEYWORD_OVERLAP_THRESHOLD

    async def _fetch_from_pubmed(self, topic: str) -> str | None:
        """Search PubMed and return a formatted context string, or None if nothing relevant found."""
        queries = self._build_pubmed_queries(topic)
        en_queries = await self._translate_queries(queries)
        logger.info("pubmed_fallback_started", queries=en_queries)

        results = await asyncio.gather(
            *[self.pubmed.search_and_fetch(q, max_results=2) for q in en_queries],
            return_exceptions=True,
        )

        # Collect articles paired with their corresponding en_query
        articles_with_query: list[tuple[PubMedArticle, str]] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning("pubmed_fallback_query_failed", error=str(result))
                continue
            for article in result:
                articles_with_query.append((article, en_queries[i]))

        # Deduplicate by uid
        seen: set[str] = set()
        unique: list[tuple[PubMedArticle, str]] = []
        for article, query in articles_with_query:
            if article["uid"] not in seen:
                seen.add(article["uid"])
                unique.append((article, query))

        if not unique:
            return None

        context_parts: list[str] = []
        for article, en_query in unique:
            combined = f"{article['title']} {article['abstract']}"
            # Check overlap between the English query and the English abstract
            if not self._has_keyword_overlap_en(en_query, combined):
                logger.warning(
                    "pubmed_article_rejected_low_keyword_overlap",
                    uid=article["uid"],
                    title=article["title"][:80],
                )
                continue
            context_parts.append(
                f"--- PubMed: {article['title']} | {article['url']} ---\n"
                f"{article['abstract']}"
            )

        if not context_parts:
            logger.warning("pubmed_all_articles_rejected_keyword_overlap")
            return None

        return "\n\n".join(context_parts)

    async def _fetch_from_web(self, url: str) -> str | None:
        """Delegate scraping to WebScraper so implementation changes don't affect this class."""
        return await self.web_scraper.scrape(url)

    async def get_medical_context(
        self, topic: str, source_url: str | None = None
    ) -> tuple[str, str]:
        """Return a (context_text, status) tuple aggregated from Qdrant, PubMed, and optional web source."""
        logger.info("fetching_medical_context", topic=topic, source_url=source_url)

        # 0. Run web scraping and Qdrant retrieval in parallel
        qdrant_task = asyncio.create_task(self._fetch_from_qdrant(topic))
        web_task = (
            asyncio.create_task(self._fetch_from_web(source_url))
            if source_url
            else None
        )

        unique_nodes = await qdrant_task
        web_context = await web_task if web_task else None

        # 1. Qdrant returned nothing
        if not unique_nodes:
            logger.warning("no_medical_context_in_qdrant", topic=topic)
            pubmed_context = await self._fetch_from_pubmed(topic)
            rag_context = pubmed_context or NO_CONTEXT_SIGNAL
            status = "ПОВНИЙ" if pubmed_context else "ВІДСУТНІЙ"
            return self._merge_web(web_context, rag_context, status)

        relevant_nodes = [
            n for n in unique_nodes if (n.score or 0.0) >= RELEVANCE_THRESHOLD
        ]

        logger.info(
            "medical_context_filtered",
            total=len(unique_nodes),
            relevant=len(relevant_nodes),
            threshold=RELEVANCE_THRESHOLD,
        )

        # 2. Qdrant has relevant chunks — filter by keyword overlap
        if relevant_nodes:
            context_parts: list[str] = []
            for node in relevant_nodes:
                content = re.sub(r"\n{3,}", "\n\n", node.get_content()).strip()

                if not self._has_keyword_overlap(topic, content):
                    logger.warning(
                        "chunk_rejected_low_keyword_overlap",
                        source=node.metadata.get("file_name", "Unknown"),
                        score=round(node.score or 0.0, 3),
                    )
                    continue

                source = node.metadata.get("file_name", "Unknown Source")
                score = round(node.score or 0.0, 3)
                context_parts.append(
                    f"--- Джерело: {source} | score: {score} ---\n{content}"
                )

            if context_parts:
                logger.info("medical_context_fetched", chunks=len(context_parts))
                return self._merge_web(
                    web_context, "\n\n".join(context_parts), "ПОВНИЙ"
                )

            # All chunks rejected due to low keyword overlap — fall back to PubMed
            logger.warning("all_chunks_rejected_keyword_overlap_fallback_pubmed")
            pubmed_context = await self._fetch_from_pubmed(topic)
            rag_context = pubmed_context or LOW_RELEVANCE_SIGNAL
            status = "ПОВНИЙ" if pubmed_context else "ОБМЕЖЕНИЙ"
            return self._merge_web(web_context, rag_context, status)

        # 3. unique_nodes is non-empty but no node meets the relevance score threshold
        logger.warning("no_relevant_nodes_found_fallback_pubmed")
        pubmed_context = await self._fetch_from_pubmed(topic)
        rag_context = pubmed_context or LOW_RELEVANCE_SIGNAL
        status = "ПОВНИЙ" if pubmed_context else "ОБМЕЖЕНИЙ"
        return self._merge_web(web_context, rag_context, status)

    @staticmethod
    def _merge_web(
        web_context: str | None, rag_context: str, status: str
    ) -> tuple[str, str]:
        """Prepend web_context to rag_context. If web context is present, status is always FULL."""
        if not web_context:
            return rag_context, status
        return f"{web_context}\n\n{rag_context}", "ПОВНИЙ"
