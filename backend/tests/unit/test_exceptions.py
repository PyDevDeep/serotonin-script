"""
Tests for backend.services.exceptions.

Coverage:
- DraftNotFoundError: message, draft_id attribute, inheritance
- PublishingFailedError: message, platform/reason attributes, inheritance
- UnsupportedPlatformError: message, platform attribute, inheritance
"""

import pytest

from backend.models.enums import Platform
from backend.services.exceptions import (
    DomainError,
    DraftNotFoundError,
    PublishingFailedError,
    UnsupportedPlatformError,
)


@pytest.mark.unit
class TestDraftNotFoundError:
    def test_message_contains_draft_id(self) -> None:
        err = DraftNotFoundError(42)
        assert "42" in str(err)

    def test_draft_id_attribute_int(self) -> None:
        err = DraftNotFoundError(7)
        assert err.draft_id == 7

    def test_draft_id_attribute_str(self) -> None:
        err = DraftNotFoundError("abc-123")
        assert err.draft_id == "abc-123"

    def test_is_domain_error(self) -> None:
        assert isinstance(DraftNotFoundError(1), DomainError)

    def test_is_exception(self) -> None:
        assert isinstance(DraftNotFoundError(1), Exception)


@pytest.mark.unit
class TestPublishingFailedError:
    def test_message_contains_platform_and_reason(self) -> None:
        err = PublishingFailedError(Platform.TELEGRAM, "HTTP 500")
        assert Platform.TELEGRAM.value in str(err) or "TELEGRAM" in str(err)
        assert "HTTP 500" in str(err)

    def test_platform_attribute(self) -> None:
        err = PublishingFailedError(Platform.TWITTER, "timeout")
        assert err.platform == Platform.TWITTER

    def test_reason_attribute(self) -> None:
        err = PublishingFailedError(Platform.THREADS, "connection refused")
        assert err.reason == "connection refused"

    def test_accepts_plain_string_platform(self) -> None:
        err = PublishingFailedError("instagram", "not supported")
        assert err.platform == "instagram"

    def test_is_domain_error(self) -> None:
        assert isinstance(PublishingFailedError(Platform.TELEGRAM, "x"), DomainError)


@pytest.mark.unit
class TestUnsupportedPlatformError:
    def test_message_contains_platform(self) -> None:
        err = UnsupportedPlatformError("tiktok")
        assert "tiktok" in str(err)

    def test_platform_attribute(self) -> None:
        err = UnsupportedPlatformError("mastodon")
        assert err.platform == "mastodon"

    def test_is_domain_error(self) -> None:
        assert isinstance(UnsupportedPlatformError("x"), DomainError)
