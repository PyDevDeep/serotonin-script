"""Unit tests for Redis sliding-window rate limiter (rate_limit.py).

Covers:
- _client_key: X-Forwarded-For (single IP, multi-IP), request.client fallback, unknown
- check_rate_limit: under limit, at limit, over limit (429), Redis pipeline calls
- Sliding-window boundary: count == requests (allowed), count == requests+1 (rejected)
- rate_limited decorator: extracts Request from kwargs and args, raises on missing Request
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.middleware.rate_limit import (
    RateLimit,
    _client_key,
    check_rate_limit,
    rate_limited,
)

TEST_LIMIT = RateLimit(requests=5, window_seconds=60, key_prefix="rl:test")


# ---------------------------------------------------------------------------
# _client_key
# ---------------------------------------------------------------------------


def _req(
    forwarded_for: str | None = None, client_host: str | None = "1.2.3.4"
) -> MagicMock:
    req = MagicMock()
    req.headers = {}
    if forwarded_for is not None:
        req.headers["X-Forwarded-For"] = forwarded_for
    req.client = MagicMock(host=client_host) if client_host else None
    return req


def test_client_key_uses_forwarded_for_first_ip():
    req = _req(forwarded_for="10.0.0.1, 10.0.0.2")
    key = _client_key(req, "rl:test")
    assert key == "rl:test:10.0.0.1"


def test_client_key_single_forwarded_for():
    req = _req(forwarded_for="192.168.1.5")
    assert _client_key(req, "rl:test") == "rl:test:192.168.1.5"


def test_client_key_falls_back_to_client_host():
    req = _req(forwarded_for=None, client_host="9.9.9.9")
    assert _client_key(req, "rl:test") == "rl:test:9.9.9.9"


def test_client_key_unknown_when_no_client():
    req = _req(forwarded_for=None, client_host=None)
    assert _client_key(req, "rl:test") == "rl:test:unknown"


# ---------------------------------------------------------------------------
# check_rate_limit — helpers
# ---------------------------------------------------------------------------


def _mock_pipeline(count: int) -> MagicMock:
    """Return a mock Redis pipeline whose execute() returns [_, _, count, _]."""
    pipe = MagicMock()
    pipe.zremrangebyscore = MagicMock()
    pipe.zadd = MagicMock()
    pipe.zcard = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, 1, count, True])
    return pipe


def _mock_redis(count: int) -> MagicMock:
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=_mock_pipeline(count))
    return redis


# ---------------------------------------------------------------------------
# check_rate_limit — behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_limit_does_not_raise():
    req = _req()
    with patch(
        "backend.api.middleware.rate_limit.get_redis", return_value=_mock_redis(3)
    ):
        await check_rate_limit(req, TEST_LIMIT)  # count=3 ≤ 5, no exception


@pytest.mark.asyncio
async def test_at_limit_does_not_raise():
    """Exactly at the limit (count == requests) is still allowed."""
    req = _req()
    with patch(
        "backend.api.middleware.rate_limit.get_redis", return_value=_mock_redis(5)
    ):
        await check_rate_limit(req, TEST_LIMIT)  # count=5 == 5, allowed


@pytest.mark.asyncio
async def test_over_limit_raises_429():
    """count == requests+1 must raise 429."""
    req = _req()
    with patch(
        "backend.api.middleware.rate_limit.get_redis", return_value=_mock_redis(6)
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(req, TEST_LIMIT)
    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail


@pytest.mark.asyncio
async def test_429_includes_retry_after_header():
    req = _req()
    with patch(
        "backend.api.middleware.rate_limit.get_redis", return_value=_mock_redis(99)
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(req, TEST_LIMIT)
    headers = exc_info.value.headers
    assert headers is not None
    assert "Retry-After" in headers
    assert headers["Retry-After"] == str(TEST_LIMIT.window_seconds)


@pytest.mark.asyncio
async def test_pipeline_commands_called():
    """Verify the correct Redis pipeline commands are issued."""
    req = _req()
    redis = _mock_redis(1)
    pipe = redis.pipeline.return_value
    with patch("backend.api.middleware.rate_limit.get_redis", return_value=redis):
        await check_rate_limit(req, TEST_LIMIT)

    pipe.zremrangebyscore.assert_called_once()
    pipe.zadd.assert_called_once()
    pipe.zcard.assert_called_once()
    pipe.expire.assert_called_once()
    pipe.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# rate_limited decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_passes_request_from_kwargs():
    req = _req()
    called_with: list[MagicMock] = []

    @rate_limited(TEST_LIMIT)
    async def handler(request: MagicMock) -> str:
        called_with.append(request)
        return "ok"

    with patch(
        "backend.api.middleware.rate_limit.check_rate_limit", new_callable=AsyncMock
    ) as mock_check:
        result = await handler(request=req)

    mock_check.assert_awaited_once_with(req, TEST_LIMIT)
    assert result == "ok"
    assert called_with[0] is req


@pytest.mark.asyncio
async def test_rate_limited_finds_request_in_positional_args():
    """Decorator must find a real Request instance passed as a positional arg."""
    from fastapi import FastAPI, Request
    from starlette.testclient import TestClient

    app = FastAPI()

    @app.get("/test")
    @rate_limited(TEST_LIMIT)
    async def handler(request: Request) -> dict[str, bool]:
        return {"ok": True}

    _ = handler  # consumed by app router; silence Pylance reportUnusedFunction

    with patch(
        "backend.api.middleware.rate_limit.check_rate_limit",
        new_callable=AsyncMock,
    ) as mock_check:
        with TestClient(app) as client:
            resp = client.get("/test")

    assert resp.status_code == 200
    mock_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limited_raises_runtime_error_without_request():
    @rate_limited(TEST_LIMIT)
    async def handler(x: int) -> str:
        return "ok"

    with pytest.raises(RuntimeError, match="request: Request"):
        await handler(x=42)


@pytest.mark.asyncio
async def test_rate_limited_propagates_429():
    req = _req()

    @rate_limited(TEST_LIMIT)
    async def handler(request: MagicMock) -> str:
        return "ok"  # pragma: no cover

    with patch(
        "backend.api.middleware.rate_limit.check_rate_limit",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=429, detail="Rate limit exceeded"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await handler(request=req)

    assert exc_info.value.status_code == 429
