from typing import Annotated

from taskiq import TaskiqDepends

from backend.integrations.llm.router import LLMRouter
from backend.services.content_generator import ContentGenerator
from backend.services.fact_checker import FactChecker
from backend.services.style_matcher import StyleMatcher


def get_llm_router() -> LLMRouter:
    """Ініціалізує та повертає роутер моделей."""
    return LLMRouter()


def get_style_matcher() -> StyleMatcher:
    """Ініціалізує сервіс пошуку стилю."""
    return StyleMatcher()


def get_fact_checker(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
) -> FactChecker:
    """Ініціалізує сервіс перевірки фактів, ін'єктуючи роутер."""
    return FactChecker(llm_router=llm_router)


def get_content_generator(
    llm_router: Annotated[LLMRouter, TaskiqDepends(get_llm_router)],
) -> ContentGenerator:
    """
    Фабрика для генератора контенту.
    Використовує спільний інстанс роутера для оптимізації ресурсів.
    """
    return ContentGenerator(llm_router=llm_router)


# Заглушка для Milestone 7.4 (Publisher Service)
# def get_publisher_service() -> PublisherService:
#     return PublisherService()
