from typing import Annotated, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from backend.api.dependencies import async_session_maker
from backend.config.settings import settings
from backend.integrations.external.pubmed_client import PubMedClient
from backend.integrations.external.web_scraper import WebScraper
from backend.integrations.llm.router import LLMRouter
from backend.models.enums import Platform
from backend.rag.pipelines.hybrid_search import HybridRetrieverPipeline
from backend.services.content_generator import ContentGenerator
from backend.services.fact_checker import FactChecker
from backend.services.publisher_service import N8nPublisher, PublisherService
from backend.services.style_matcher import StyleMatcher


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI and Taskiq dependencies."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_llm_router() -> LLMRouter:
    """Initialise and return the LLM router."""
    return LLMRouter()


def get_style_matcher() -> StyleMatcher:
    """Initialise and return the style matcher service."""
    retriever = HybridRetrieverPipeline.build(collection_name="doctor_style", top_k=5)
    return StyleMatcher(retriever=retriever)


def get_fact_checker(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
) -> FactChecker:
    """Initialise the fact-checker service with all required infrastructure dependencies."""
    retriever = HybridRetrieverPipeline.build(
        collection_name="medical_knowledge", top_k=2
    )
    return FactChecker(
        retriever=retriever,
        pubmed=PubMedClient(),
        web_scraper=WebScraper(),
        llm_router=llm_router,
    )


def get_publisher_service() -> PublisherService:
    """Build PublisherService with one N8nPublisher per platform."""
    publishers = {
        platform: N8nPublisher(webhook_url=settings.N8N_WEBHOOK_URL, platform=platform)
        for platform in Platform
    }
    return PublisherService(publishers=publishers)


def get_content_generator(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
    style_matcher: Annotated[StyleMatcher, TaskiqDepends(get_style_matcher)],
    fact_checker: Annotated[FactChecker, TaskiqDepends(get_fact_checker)],
) -> ContentGenerator:
    """Initialise the content generator, sharing infrastructure instances to save resources."""
    return ContentGenerator(
        llm_router=llm_router,
        style_matcher=style_matcher,
        fact_checker=fact_checker,
    )
