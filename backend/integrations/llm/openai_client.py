from llama_index.llms.openai import OpenAI

from backend.config.settings import settings


def get_openai_llm() -> OpenAI:
    """Fallback модель GPT-4o."""
    return OpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY.get_secret_value(),
        temperature=settings.OPENAI_TEMPERATURE,
        max_tokens=2048,
    )


def get_cheap_openai_llm() -> OpenAI:
    """Модель для економії бюджету на великих контекстах."""
    return OpenAI(
        model="gpt-4o-mini",
        api_key=settings.OPENAI_API_KEY.get_secret_value(),
        temperature=settings.OPENAI_TEMPERATURE,
        max_tokens=2048,
    )
