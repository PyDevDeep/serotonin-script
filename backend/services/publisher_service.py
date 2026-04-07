from abc import ABC, abstractmethod
from collections.abc import Mapping

import structlog

from backend.models.enums import Platform
from backend.services.exceptions import PublishingFailedError, UnsupportedPlatformError

logger = structlog.get_logger()


class SocialPublisher(ABC):
    """Contract that every platform integration must implement."""

    @abstractmethod
    async def publish(self, post_id: str, content: str) -> None:
        """Publish content. Raise PublishingFailedError on failure."""


class N8nPublisher(SocialPublisher):
    """Delegates publishing to the n8n webhook orchestrator."""

    def __init__(self, webhook_url: str, platform: Platform) -> None:
        self._webhook_url = webhook_url
        self._platform = platform

    async def publish(self, post_id: str, content: str) -> None:
        import httpx

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
