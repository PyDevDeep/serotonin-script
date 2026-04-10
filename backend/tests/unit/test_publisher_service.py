"""
Tests for backend.services.publisher_service.

Coverage:
- PublisherService.publish: success, unsupported platform, publishing failure
- N8nPublisher.publish: success, HTTP error, generic exception
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models.enums import Platform
from backend.services.exceptions import (
    ContentTooLongError,
    PublishingFailedError,
    UnsupportedPlatformError,
)
from backend.services.publisher_service import (
    PLATFORM_CHAR_LIMITS,
    N8nPublisher,
    PublisherService,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_telegram_publisher() -> AsyncMock:
    m = AsyncMock()
    m.publish = AsyncMock()
    return m


@pytest.fixture
def publisher_service(mock_telegram_publisher: AsyncMock) -> PublisherService:
    return PublisherService(publishers={Platform.TELEGRAM: mock_telegram_publisher})


# ---------------------------------------------------------------------------
# TestPublisherService
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPublisherService:
    """PublisherService routes to the correct publisher or raises on unknown platform."""

    @pytest.mark.asyncio
    async def test_dispatches_to_correct_publisher(
        self, publisher_service: PublisherService, mock_telegram_publisher: AsyncMock
    ) -> None:
        await publisher_service.publish("post-1", "telegram", "content")
        mock_telegram_publisher.publish.assert_awaited_once_with("post-1", "content")

    @pytest.mark.asyncio
    async def test_unknown_platform_string_raises_unsupported(
        self, publisher_service: PublisherService
    ) -> None:
        with pytest.raises(UnsupportedPlatformError) as exc_info:
            await publisher_service.publish("post-1", "tiktok", "content")
        assert exc_info.value.platform == "tiktok"

    @pytest.mark.asyncio
    async def test_valid_platform_without_registered_publisher_raises(self) -> None:
        # TWITTER is a valid Platform enum value but not registered
        service = PublisherService(publishers={Platform.TELEGRAM: AsyncMock()})
        with pytest.raises(UnsupportedPlatformError):
            await service.publish("post-1", "twitter", "content")

    @pytest.mark.asyncio
    async def test_publisher_raises_publishing_failed_error_propagates(
        self, publisher_service: PublisherService, mock_telegram_publisher: AsyncMock
    ) -> None:
        mock_telegram_publisher.publish.side_effect = PublishingFailedError(
            Platform.TELEGRAM, "HTTP 503"
        )
        with pytest.raises(PublishingFailedError, match="HTTP 503"):
            await publisher_service.publish("post-1", "telegram", "content")

    @pytest.mark.asyncio
    async def test_all_registered_platforms_dispatch(self) -> None:
        publishers = {p: AsyncMock() for p in Platform}
        service = PublisherService(publishers=publishers)
        for platform in Platform:
            await service.publish("post-1", platform.value, "text")
            publishers[platform].publish.assert_awaited_once_with("post-1", "text")
            publishers[platform].reset_mock()


# ---------------------------------------------------------------------------
# TestN8nPublisher
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestN8nPublisher:
    """N8nPublisher.publish sends correct payload and handles HTTP errors."""

    @pytest.fixture
    def publisher(self) -> N8nPublisher:
        return N8nPublisher(
            webhook_url="http://n8n:5678/webhook/publish-post",
            platform=Platform.TELEGRAM,
        )

    @pytest.mark.asyncio
    async def test_success_posts_correct_payload(self, publisher: N8nPublisher) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await publisher.publish("post-42", "Hello world")

        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["post_id"] == "post-42"
        assert payload["platform"] == "telegram"
        assert payload["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_http_status_error_raises_publishing_failed(
        self, publisher: N8nPublisher
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = http_error
            mock_client_cls.return_value = mock_client

            with pytest.raises(PublishingFailedError) as exc_info:
                await publisher.publish("post-1", "text")

        assert exc_info.value.platform == Platform.TELEGRAM
        assert "503" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_generic_exception_raises_publishing_failed(
        self, publisher: N8nPublisher
    ) -> None:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = ConnectionError("network unreachable")
            mock_client_cls.return_value = mock_client

            with pytest.raises(PublishingFailedError) as exc_info:
                await publisher.publish("post-1", "text")

        assert "network unreachable" in exc_info.value.reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize("platform", [Platform.THREADS, Platform.TWITTER])
    async def test_content_at_limit_is_allowed(self, platform: Platform) -> None:
        publisher = N8nPublisher(
            webhook_url="http://n8n:5678/webhook/publish-post",
            platform=platform,
        )
        limit = PLATFORM_CHAR_LIMITS[platform]
        content = "x" * limit

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await publisher.publish("post-1", content)  # must not raise

    @pytest.mark.asyncio
    @pytest.mark.parametrize("platform", [Platform.THREADS, Platform.TWITTER])
    async def test_content_over_limit_raises_content_too_long(
        self, platform: Platform
    ) -> None:
        publisher = N8nPublisher(
            webhook_url="http://n8n:5678/webhook/publish-post",
            platform=platform,
        )
        limit = PLATFORM_CHAR_LIMITS[platform]
        content = "x" * (limit + 1)

        with pytest.raises(ContentTooLongError) as exc_info:
            await publisher.publish("post-1", content)

        assert exc_info.value.platform == platform
        assert exc_info.value.limit == limit
        assert exc_info.value.actual == limit + 1

    @pytest.mark.asyncio
    async def test_content_too_long_does_not_call_http(self) -> None:
        publisher = N8nPublisher(
            webhook_url="http://n8n:5678/webhook/publish-post",
            platform=Platform.THREADS,
        )
        content = "x" * 501

        with patch("httpx.AsyncClient") as mock_client_cls:
            with pytest.raises(ContentTooLongError):
                await publisher.publish("post-1", content)

        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_has_no_char_limit(self) -> None:
        publisher = N8nPublisher(
            webhook_url="http://n8n:5678/webhook/publish-post",
            platform=Platform.TELEGRAM,
        )
        content = "x" * 5000

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await publisher.publish("post-1", content)  # must not raise
