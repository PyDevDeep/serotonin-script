import json
from typing import Any

import structlog
from llama_index.core.llms import ChatMessage, MessageRole

from backend.agents.prompts.system_prompts import (
    BASE_GENERATION_PROMPT_ANTHROPIC,
    BASE_GENERATION_PROMPT_OPENAI,
    DATA_BLOCK_TEMPLATE,
    JUDGE_SYSTEM,
    JUDGE_USER,
    RETRY_INJECTION,
    RETRY_INJECTION_OPENAI,
)
from backend.integrations.llm.router import LLMRouter
from backend.services.fact_checker import FactChecker
from backend.services.style_matcher import StyleMatcher

logger = structlog.get_logger()


class ContentGenerator:
    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self.llm_router = llm_router or LLMRouter()
        self.style_matcher = StyleMatcher()
        self.fact_checker = FactChecker(llm_router=self.llm_router)

    async def _judge_limited(
        self, post: str, topic: str, status: str
    ) -> dict[str, Any]:
        judge_messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=JUDGE_SYSTEM),
            ChatMessage(
                role=MessageRole.USER,
                content=JUDGE_USER.format(status=status, topic=topic, post=post),
            ),
        ]
        raw_content: str = ""
        try:
            response = await self.llm_router.achat_with_fallback(
                primary_messages=judge_messages,
                fallback_messages=judge_messages,
            )
            raw_content = response.message.content or ""

            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()

            return json.loads(cleaned)

        except (json.JSONDecodeError, Exception) as e:
            logger.warning("judge_error", error=str(e), raw=raw_content[:100])
            return {
                "pass": False,
                "violations": [{"sentence": "system", "reason": str(e)}],
            }

    async def generate_draft(
        self,
        topic: str,
        platform: str,
        source_url: str | None = None,
        max_retries: int = 2,
    ) -> str:
        logger.info(
            "draft_generation_started",
            topic=topic,
            platform=platform,
            source_url=source_url,
        )

        style_context = await self.style_matcher.get_style_context(topic)
        medical_context, context_status = await self.fact_checker.get_medical_context(
            topic, source_url=source_url
        )

        # Робимо перевірку статусу стійкою до зайвих лапок або пробілів
        clean_status = context_status.strip().replace("'", "").replace('"', "").upper()
        is_limited = clean_status == "ОБМЕЖЕНИЙ"

        current_medical_context = medical_context
        result = ""

        for attempt in range(max_retries + 1):
            data_block = DATA_BLOCK_TEMPLATE.format(
                platform=platform,
                topic=topic,
                style_context=style_context,
                medical_context=current_medical_context,
                context_status=context_status,
            )

            # Генерація контенту (Anthropic/OpenAI)
            response = await self.llm_router.achat_with_fallback(
                primary_messages=[
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=BASE_GENERATION_PROMPT_ANTHROPIC,
                    ),
                    ChatMessage(role=MessageRole.USER, content=data_block),
                ],
                fallback_messages=[
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=BASE_GENERATION_PROMPT_OPENAI["system"],
                    ),
                    ChatMessage(role=MessageRole.USER, content=data_block),
                ],
            )
            result = response.message.content or ""

            if not is_limited:
                break

            # Валідація (Judge) — викликаємо ОДИН раз за ітерацію
            judge_result = await self._judge_limited(result, topic, context_status)

            logger.info(
                "judge_check",
                attempt=attempt,
                passed=judge_result.get("pass"),
                violations=judge_result.get("violations", []),  # ← додай це
            )

            if judge_result["pass"]:
                break

            if attempt < max_retries:
                violations_text = "\n".join(
                    f'- "{v["sentence"]}" → {v["reason"]}'
                    for v in judge_result.get("violations", [])
                )
                injection = (
                    RETRY_INJECTION_OPENAI
                    if response.provider == "openai"
                    else RETRY_INJECTION
                )
                current_medical_context = medical_context + injection.format(
                    attempt=attempt + 1, violations=violations_text
                )
            else:
                logger.warning(
                    "judge_failed_after_retries",
                    topic=topic,
                    attempts=max_retries + 1,
                )
                # Передаємо останній згенерований варіант (result) у виняток
                raise JudgeFailedError(
                    topic=topic, attempts=max_retries + 1, draft=result
                )
        return result


class JudgeFailedError(Exception):
    # Додаємо аргумент draft
    def __init__(self, topic: str, attempts: int, draft: str):
        super().__init__(f"Judge failed after {attempts} attempts for topic: '{topic}'")
        self.topic = topic
        self.attempts = attempts
        self.draft = draft  # Зберігаємо текст для подальшого використання
