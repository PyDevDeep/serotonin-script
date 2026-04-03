from llama_index.llms.anthropic import Anthropic

from backend.config.settings import settings


def get_anthropic_llm() -> Anthropic:
    """Ініціалізує основну модель Claude"""
    return Anthropic(
        model=settings.ANTHROPIC_MODEL,
        api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
        temperature=settings.ANTHROPIC_TEMPERATURE,
        max_tokens=2048,
    )
