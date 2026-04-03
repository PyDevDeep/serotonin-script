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
from backend.rag.pipelines.hybrid_search import HybridRetrieverPipeline

logger = structlog.get_logger()

RELEVANCE_THRESHOLD = 0.7
KEYWORD_OVERLAP_THRESHOLD = 0.15
PUBMED_KEYWORD_OVERLAP_THRESHOLD = 0.5
LOW_RELEVANCE_SIGNAL = "[КОНТЕКСТ ОБМЕЖЕНИЙ]: Знайдені матеріали частково стосуються теми. Використовуй лише загальні рекомендації без клінічних тверджень про конкретні препарати."
NO_CONTEXT_SIGNAL = "[КОНТЕКСТ ВІДСУТНІЙ]: Матеріали по темі не знайдені. Не генеруй клінічних тверджень."


class FactChecker:
    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self.retriever = HybridRetrieverPipeline(
            collection_name="medical_knowledge", top_k=2
        )
        self.pubmed = PubMedClient()
        self.web_scraper = WebScraper()
        self.llm_router = llm_router or LLMRouter()

    def _build_queries(self, topic: str) -> list[str]:
        """Для Qdrant — повертає тему як є."""
        return [topic]

    def _build_pubmed_queries(self, topic: str) -> list[str]:
        clean = re.split(r"[?—]", topic)[0].strip()  # ← тільки один раз на початку

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
        ).strip()  # ← прибираємо хвостові символи після очищення

        return [clean] if clean else [topic]

    def _deduplicate(self, nodes: list[NodeWithScore]) -> list[NodeWithScore]:
        seen: set[str] = set()
        result: list[NodeWithScore] = []
        for node in nodes:
            node_id = node.node.node_id
            if node_id not in seen:
                seen.add(node_id)
                result.append(node)
        return result

    def _extract_keywords(self, text: str) -> set[str]:
        """Витягує значущі слова з тексту — фільтрує стоп-слова."""
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
        """
        Перевіряє чи є достатній тематичний overlap між темою і текстом chunk.
        Повертає False якщо chunk семантично близький але тематично нерелевантний.
        """
        topic_keywords = self._extract_keywords(topic)
        if not topic_keywords:
            return True  # якщо не можемо перевірити — пропускаємо

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
        """Перекладає українські підзапити на англійську для PubMed через LLMRouter."""
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
        """
        Перевіряє overlap між англійським запитом і англійським абстрактом.
        Використовується для PubMed де і запит і контент англійською.
        """
        query_keywords = self._extract_keywords(translated_query)
        if not query_keywords:
            return True

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
        queries = self._build_pubmed_queries(topic)
        en_queries = await self._translate_queries(queries)
        logger.info("pubmed_fallback_started", queries=en_queries)

        results = await asyncio.gather(
            *[self.pubmed.search_and_fetch(q, max_results=2) for q in en_queries],
            return_exceptions=True,
        )

        # Збираємо статті разом з відповідним en_query
        articles_with_query: list[tuple[PubMedArticle, str]] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning("pubmed_fallback_query_failed", error=str(result))
                continue
            for article in result:
                articles_with_query.append((article, en_queries[i]))

        # Дедуплікація за uid
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
            # Перевіряємо overlap між англійським запитом і англійським абстрактом
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
        """Делегує scraping у WebScraper — заміна реалізації не торкається цього класу."""
        return await self.web_scraper.scrape(url)

    async def get_medical_context(
        self, topic: str, source_url: str | None = None
    ) -> tuple[str, str]:
        logger.info("fetching_medical_context", topic=topic, source_url=source_url)

        # 0. Web scraping та Qdrant — запускаємо паралельно
        qdrant_task = asyncio.create_task(self._fetch_from_qdrant(topic))
        web_task = (
            asyncio.create_task(self._fetch_from_web(source_url))
            if source_url
            else None
        )

        unique_nodes = await qdrant_task
        web_context = await web_task if web_task else None

        # 1. Qdrant порожній
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

        # 2. Qdrant має релевантні chunks — фільтруємо за keyword overlap
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

            # Всі chunks відкинуті через низький keyword overlap — fallback до PubMed
            logger.warning("all_chunks_rejected_keyword_overlap_fallback_pubmed")
            pubmed_context = await self._fetch_from_pubmed(topic)
            rag_context = pubmed_context or LOW_RELEVANCE_SIGNAL
            status = "ПОВНИЙ" if pubmed_context else "ОБМЕЖЕНИЙ"
            return self._merge_web(web_context, rag_context, status)

        # 3. unique_nodes не порожній, але немає жодного relevant_node (score < threshold)
        logger.warning("no_relevant_nodes_found_fallback_pubmed")
        pubmed_context = await self._fetch_from_pubmed(topic)
        rag_context = pubmed_context or LOW_RELEVANCE_SIGNAL
        status = "ПОВНИЙ" if pubmed_context else "ОБМЕЖЕНИЙ"
        return self._merge_web(web_context, rag_context, status)

    @staticmethod
    def _merge_web(
        web_context: str | None, rag_context: str, status: str
    ) -> tuple[str, str]:
        """Prepend web_context до rag_context. Якщо web є — статус завжди ПОВНИЙ."""
        if not web_context:
            return rag_context, status
        return f"{web_context}\n\n{rag_context}", "ПОВНИЙ"
