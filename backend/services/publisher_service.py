from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING

import httpx
import structlog

from backend.models.enums import Platform
from backend.services.exceptions import (
    ContentTooLongError,
    PublishingFailedError,
    UnsupportedPlatformError,
)

if TYPE_CHECKING:
    from orchestration.monitoring.n8n_health_check import N8nHealthChecker

logger = structlog.get_logger()


class SocialPublisher(ABC):
    """Contract that every platform integration must implement."""

    @abstractmethod
    async def publish(self, post_id: str, content: str) -> None:
        """Publish content. Raise PublishingFailedError on failure."""


PLATFORM_CHAR_LIMITS: dict[Platform, int] = {
    Platform.THREADS: 500,
    Platform.TWITTER: 280,
}


class N8nPublisher(SocialPublisher):
    """Delegates publishing to the n8n webhook orchestrator.

    Args:
        webhook_url:    n8n webhook endpoint.
        platform:       target social platform.
        health_checker: optional circuit breaker; when provided, guard() is called
                        before each request so failures are surfaced immediately
                        instead of hanging until httpx timeout.
    """

    def __init__(
        self,
        webhook_url: str,
        platform: Platform,
        health_checker: N8nHealthChecker | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._platform = platform
        self._health_checker = health_checker

    async def publish(self, post_id: str, content: str) -> None:
        limit = PLATFORM_CHAR_LIMITS.get(self._platform)
        if limit is not None and len(content) > limit:
            raise ContentTooLongError(self._platform, limit, len(content))

        from orchestration.monitoring.n8n_health_check import N8nUnavailableError

        if self._health_checker is not None:
            try:
                self._health_checker.guard()
            except N8nUnavailableError as exc:
                raise PublishingFailedError(self._platform, str(exc)) from exc

        payload = {
            "post_id": post_id,
            "platform": self._platform.value,
            "content": content,
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._webhook_url, json=payload, timeout=10.0
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PublishingFailedError(
                self._platform, f"HTTP {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise PublishingFailedError(self._platform, str(exc)) from exc


class PublisherService:
    """Routes publish requests to the correct SocialPublisher by platform name."""

    def __init__(self, publishers: Mapping[Platform, SocialPublisher]) -> None:
        self._publishers = publishers

    async def publish(self, post_id: str, platform: str, content: str) -> None:
        """Dispatch to the registered publisher for the given platform.

        Raises:
            UnsupportedPlatformError: if no publisher is registered for the platform.
            PublishingFailedError: if the publisher reports a delivery failure.
        """
        try:
            key = Platform(platform)
        except ValueError as err:
            raise UnsupportedPlatformError(platform) from err

        publisher = self._publishers.get(key)
        if publisher is None:
            raise UnsupportedPlatformError(platform)

        logger.info("publisher_service_dispatching", post_id=post_id, platform=platform)
        await publisher.publish(post_id, content)
        logger.info("publisher_service_success", post_id=post_id, platform=platform)
