"""
Tests for backend.api.middleware.error_handler.

Coverage:
- _problem: RFC 7807 body structure, extra fields merging, correct status code
- domain_exception_handler: DraftNotFoundError → 404, UnsupportedPlatformError → 422,
  PublishingFailedError → 502, unknown DomainError subclass → 400
- global_exception_handler: any Exception → 500, detail is generic (no sensitive info),
  error type logged via structlog (not leaked in response)
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status

from backend.api.middleware.error_handler import (
    _problem,
    domain_exception_handler,
    global_exception_handler,
)
from backend.models.enums import Platform
from backend.services.exceptions import (
    DomainError,
    DraftNotFoundError,
    PublishingFailedError,
    UnsupportedPlatformError,
)


def _body(resp) -> dict[str, object]:
    """Decode JSONResponse body regardless of bytes/memoryview type."""
    return json.loads(bytes(resp.body))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_request() -> MagicMock:
    """Minimal FastAPI Request mock."""
    req = MagicMock()
    req.url.path = "/api/v1/drafts/42"
    req.method = "GET"
    return req


# ---------------------------------------------------------------------------
# _problem (pure helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProblem:
    def test_status_code_set_correctly(self, mock_request: MagicMock) -> None:
        resp = _problem(mock_request, 404, "Draft Not Found", "No such draft.")
        assert resp.status_code == 404

    def test_body_contains_required_rfc7807_fields(
        self, mock_request: MagicMock
    ) -> None:
        """RFC 7807 mandates: type, title, status, detail, instance."""
        resp = _problem(mock_request, 404, "Draft Not Found", "No such draft.")
        body = _body(resp)

        assert "type" in body
        assert "title" in body
        assert "status" in body
        assert "detail" in body
        assert "instance" in body

    def test_instance_is_request_path(self, mock_request: MagicMock) -> None:
        resp = _problem(mock_request, 404, "Not Found", "detail")
        body = _body(resp)

        assert body["instance"] == "/api/v1/drafts/42"

    def test_title_reflected_in_type_url(self, mock_request: MagicMock) -> None:
        """Type URL must be derived from title (lowercased, spaces → hyphens)."""
        resp = _problem(mock_request, 400, "Bad Input Data", "detail")
        body = _body(resp)

        assert "bad-input-data" in str(body["type"])

    def test_extra_fields_merged_into_body(self, mock_request: MagicMock) -> None:
        resp = _problem(mock_request, 404, "Not Found", "d", extra={"draft_id": 99})
        body = _body(resp)

        assert body["draft_id"] == 99

    def test_no_extra_fields_when_extra_is_none(self, mock_request: MagicMock) -> None:
        resp = _problem(mock_request, 500, "Error", "msg", extra=None)
        body = _body(resp)

        assert set(body.keys()) == {"type", "title", "status", "detail", "instance"}

    def test_status_numeric_in_body(self, mock_request: MagicMock) -> None:
        resp = _problem(mock_request, 422, "Unprocessable", "bad")
        body = _body(resp)

        assert body["status"] == 422


# ---------------------------------------------------------------------------
# domain_exception_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDomainExceptionHandler:
    @pytest.mark.asyncio
    async def test_draft_not_found_returns_404(self, mock_request: MagicMock) -> None:
        exc = DraftNotFoundError(42)
        resp = await domain_exception_handler(mock_request, exc)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_draft_not_found_body_contains_draft_id(
        self, mock_request: MagicMock
    ) -> None:
        exc = DraftNotFoundError(42)
        resp = await domain_exception_handler(mock_request, exc)
        body = _body(resp)

        assert str(body["draft_id"]) == "42"

    @pytest.mark.asyncio
    async def test_draft_not_found_str_id(self, mock_request: MagicMock) -> None:
        """draft_id can be a string UUID — must be preserved in response."""
        exc = DraftNotFoundError("uuid-abc-123")
        resp = await domain_exception_handler(mock_request, exc)
        body = _body(resp)

        assert body["draft_id"] == "uuid-abc-123"

    @pytest.mark.asyncio
    async def test_unsupported_platform_returns_422(
        self, mock_request: MagicMock
    ) -> None:
        exc = UnsupportedPlatformError("tiktok")
        resp = await domain_exception_handler(mock_request, exc)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_unsupported_platform_body_contains_platform(
        self, mock_request: MagicMock
    ) -> None:
        exc = UnsupportedPlatformError("tiktok")
        resp = await domain_exception_handler(mock_request, exc)
        body = _body(resp)

        assert body["platform"] == "tiktok"

    @pytest.mark.asyncio
    async def test_publishing_failed_returns_502(self, mock_request: MagicMock) -> None:
        exc = PublishingFailedError(Platform.TELEGRAM, "upstream timeout")
        resp = await domain_exception_handler(mock_request, exc)
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_publishing_failed_body_contains_platform(
        self, mock_request: MagicMock
    ) -> None:
        exc = PublishingFailedError(Platform.TWITTER, "rate limited")
        resp = await domain_exception_handler(mock_request, exc)
        body = _body(resp)

        assert body["platform"] == Platform.TWITTER.value

    @pytest.mark.asyncio
    async def test_publishing_failed_logs_error(self, mock_request: MagicMock) -> None:
        """PublishingFailedError triggers a structlog error call."""
        exc = PublishingFailedError(Platform.THREADS, "502 upstream")

        with patch("backend.api.middleware.error_handler.logger") as mock_logger:
            await domain_exception_handler(mock_request, exc)

            mock_logger.error.assert_called_once()
            assert mock_logger.error.call_args.args[0] == "publishing_failed"

    @pytest.mark.asyncio
    async def test_unknown_domain_error_returns_400(
        self, mock_request: MagicMock
    ) -> None:
        """Future DomainError subclasses not yet handled → 400 catch-all."""

        class FutureDomainError(DomainError):
            pass

        exc = FutureDomainError("something new")
        resp = await domain_exception_handler(mock_request, exc)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_unknown_domain_error_logs(self, mock_request: MagicMock) -> None:
        class AnotherDomainError(DomainError):
            pass

        exc = AnotherDomainError("edge case")

        with patch("backend.api.middleware.error_handler.logger") as mock_logger:
            await domain_exception_handler(mock_request, exc)

            mock_logger.error.assert_called_once()
            assert mock_logger.error.call_args.args[0] == "unhandled_domain_error"

    @pytest.mark.asyncio
    async def test_response_detail_contains_exception_message(
        self, mock_request: MagicMock
    ) -> None:
        """The detail field must reflect str(exc) for domain errors."""
        exc = DraftNotFoundError(7)
        resp = await domain_exception_handler(mock_request, exc)
        body = _body(resp)

        assert "7" in str(body["detail"])


# ---------------------------------------------------------------------------
# global_exception_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGlobalExceptionHandler:
    @pytest.mark.asyncio
    async def test_returns_500_for_any_exception(self, mock_request: MagicMock) -> None:
        exc = RuntimeError("something went very wrong")
        resp = await global_exception_handler(mock_request, exc)
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.asyncio
    async def test_response_body_is_generic_message(
        self, mock_request: MagicMock
    ) -> None:
        """Sensitive exception details must NOT leak into the response body."""
        exc = ValueError("db password is hunter2")
        resp = await global_exception_handler(mock_request, exc)
        body = _body(resp)

        assert body["detail"] == "An unexpected error occurred."
        assert "hunter2" not in str(body["detail"])

    @pytest.mark.asyncio
    async def test_logs_exception_type(self, mock_request: MagicMock) -> None:
        """structlog.error must be called with error_type key."""
        exc = AttributeError("missing attr")

        with patch("backend.api.middleware.error_handler.logger") as mock_logger:
            await global_exception_handler(mock_request, exc)

            mock_logger.error.assert_called_once()
            call_kwargs = mock_logger.error.call_args.kwargs
            assert call_kwargs.get("error_type") == "AttributeError"

    @pytest.mark.asyncio
    async def test_logs_request_path_and_method(self, mock_request: MagicMock) -> None:
        """Log record must include both path and method for debugging."""
        exc = Exception("boom")

        with patch("backend.api.middleware.error_handler.logger") as mock_logger:
            await global_exception_handler(mock_request, exc)

            call_kwargs = mock_logger.error.call_args.kwargs
            assert call_kwargs.get("path") == "/api/v1/drafts/42"
            assert call_kwargs.get("method") == "GET"

    @pytest.mark.asyncio
    async def test_rfc7807_structure_on_500(self, mock_request: MagicMock) -> None:
        """500 response must still conform to RFC 7807 structure."""
        exc = Exception("crash")
        resp = await global_exception_handler(mock_request, exc)
        body = _body(resp)

        for key in ("type", "title", "status", "detail", "instance"):
            assert key in body, f"Missing RFC 7807 field: {key}"

    @pytest.mark.asyncio
    async def test_handles_exception_with_empty_message(
        self, mock_request: MagicMock
    ) -> None:
        """Exception with empty string message must not crash the handler."""
        exc = Exception("")
        resp = await global_exception_handler(mock_request, exc)
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_handles_none_type_exception_args(
        self, mock_request: MagicMock
    ) -> None:
        """Exception where str() returns something unexpected must not crash handler."""
        exc = Exception(None)
        resp = await global_exception_handler(mock_request, exc)
        assert resp.status_code == 500
