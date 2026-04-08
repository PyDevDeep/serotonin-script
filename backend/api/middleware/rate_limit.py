"""Redis-backed sliding-window rate limiter for FastAPI endpoints."""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException, Request

from backend.config.settings import settings

_P = ParamSpec("_P")
_R = TypeVar("_R")


logger = structlog.get_logger()

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/1",
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


@dataclass(frozen=True)
class RateLimit:
    """Sliding-window rate limit configuration.

    Args:
        requests: Maximum number of requests allowed within the window.
        window_seconds: Duration of the sliding window in seconds.
        key_prefix: Redis key prefix to isolate this limiter from others.
    """

    requests: int
    window_seconds: int
    key_prefix: str = "rl"


# Pre-defined limits for common use-cases
SLACK_RATE_LIMIT = RateLimit(requests=30, window_seconds=60, key_prefix="rl:slack")
GENERATE_RATE_LIMIT = RateLimit(requests=5, window_seconds=60, key_prefix="rl:generate")
API_RATE_LIMIT = RateLimit(requests=100, window_seconds=60, key_prefix="rl:api")


def _client_key(request: Request, prefix: str) -> str:
    """Build a per-client Redis key.

    Uses X-Forwarded-For (first IP) when behind a proxy, falls back to
    request.client.host, and ultimately to "unknown".
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        ip = "unknown"
    return f"{prefix}:{ip}"


async def check_rate_limit(request: Request, limit: RateLimit) -> None:
    """Enforce a sliding-window rate limit using a Redis sorted set.

    Each request is recorded as a member with the current timestamp as its
    score.  Entries older than `window_seconds` are pruned before counting,
    so the window truly "slides" rather than resetting on a fixed boundary.

    Args:
        request: The incoming FastAPI request (used to extract client IP).
        limit: The :class:`RateLimit` configuration to apply.

    Raises:
        HTTPException: 429 when the client exceeds the allowed request count.
    """
    redis = get_redis()
    key = _client_key(request, limit.key_prefix)
    now = time.time()
    window_start = now - limit.window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, limit.window_seconds + 1)
    results = await pipe.execute()

    current_count: int = results[2]

    if current_count > limit.requests:
        logger.warning(
            "rate_limit_exceeded",
            key=key,
            count=current_count,
            limit=limit.requests,
            window=limit.window_seconds,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: {limit.requests} requests "
                f"per {limit.window_seconds}s allowed."
            ),
            headers={"Retry-After": str(limit.window_seconds)},
        )


def rate_limited(
    limit: RateLimit,
) -> Callable[
    [Callable[_P, Coroutine[Any, Any, _R]]], Callable[_P, Coroutine[Any, Any, _R]]
]:
    """Decorator that applies a :class:`RateLimit` to a FastAPI route handler.

    The decorated function must accept a ``request: Request`` parameter
    (positional or keyword).

    Usage::

        @router.post("/generate")
        @rate_limited(GENERATE_RATE_LIMIT)
        async def generate(request: Request, ...):
            ...
    """

    def decorator(
        func: Callable[_P, Coroutine[Any, Any, _R]],
    ) -> Callable[_P, Coroutine[Any, Any, _R]]:
        @wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            request: Request | None = kwargs.get("request")  # type: ignore[assignment]
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = cast(Request, arg)
                        break
            if request is None:
                raise RuntimeError(
                    "@rate_limited requires the handler to accept a `request: Request` argument"
                )
            await check_rate_limit(request, limit)
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
