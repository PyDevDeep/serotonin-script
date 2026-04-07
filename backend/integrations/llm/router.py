import structlog
from anthropic import BadRequestError
from llama_index.core.llms import ChatMessage, ChatResponse

from backend.config.settings import settings
from backend.integrations.llm.anthropic_client import get_anthropic_llm
from backend.integrations.llm.openai_client import get_cheap_openai_llm, get_openai_llm

logger = structlog.get_logger()


class LLMResponse:
    """Wraps a ChatResponse together with the provider name that produced it."""

    def __init__(self, response: ChatResponse, provider: str) -> None:
        """Store the response and provider identifier."""
        self.response = response
        self.provider = provider

    @property
    def message(self) -> ChatMessage:
        """Return the chat message from the underlying response."""
        return self.response.message


class LLMRouter:
    """Routes LLM requests between Anthropic (primary) and OpenAI (fallback)."""

    def __init__(self) -> None:
        """Initialise primary, fallback, and cheap LLM instances."""
        self.primary_llm = get_anthropic_llm()
        self.fallback_llm = get_openai_llm()
        self.cheap_llm = get_cheap_openai_llm()

    def _calculate_length(self, messages: list[ChatMessage]) -> int:
        """Return the total character count of all message contents."""
        return sum(len(msg.content or "") for msg in messages)

    async def achat_with_fallback(
        self,
        primary_messages: list[ChatMessage],
        fallback_messages: list[ChatMessage],
    ) -> LLMResponse:
        prompt_length = self._calculate_length(primary_messages)

        if prompt_length > settings.LLM_COST_THRESHOLD_CHARS:
            logger.warning(
                "cost_routing_triggered",
                length=prompt_length,
                threshold=settings.LLM_COST_THRESHOLD_CHARS,
                model="gpt-4o-mini",
            )
            try:
                response = await self.cheap_llm.achat(fallback_messages)
                return LLMResponse(response=response, provider="openai")
            except Exception as e:
                logger.error(
                    "cheap_llm_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    action="raise_exception",
                )
                raise

        try:
            response = await self.primary_llm.achat(primary_messages)
            return LLMResponse(response=response, provider="anthropic")
        except BadRequestError as e:
            logger.error(
                "primary_llm_bad_request",
                error=str(e),
                error_type=type(e).__name__,
                provider="anthropic",
                action="raise_no_fallback",
            )
            raise
        except Exception as e:
            logger.error(
                "primary_llm_failed",
                error=str(e),
                error_type=type(e).__name__,
                provider="anthropic",
                action="fallback_to_openai",
            )
            try:
                response = await self.fallback_llm.achat(fallback_messages)
                return LLMResponse(response=response, provider="openai")
            except Exception as fallback_error:
                logger.error(
                    "fallback_llm_failed",
                    error=str(fallback_error),
                    error_type=type(fallback_error).__name__,
                    provider="openai",
                    action="raise_exception",
                )
                raise
