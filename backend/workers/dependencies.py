from typing import Annotated, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from backend.api.dependencies import async_session_maker
from backend.integrations.llm.router import LLMRouter
from backend.services.content_generator import ContentGenerator
from backend.services.fact_checker import FactChecker
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
    return StyleMatcher()


def get_fact_checker(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
) -> FactChecker:
    """Initialise the fact-checker service with the injected LLM router."""
    return FactChecker(llm_router=llm_router)


def get_content_generator(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
) -> ContentGenerator:
    """Initialise the content generator, sharing the LLM router instance to save resources."""
    return ContentGenerator(llm_router=llm_router)
