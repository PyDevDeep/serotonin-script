"""Unit tests for Slack signature verification middleware (auth.py).

Covers:
- Missing headers (timestamp, signature, both)
- Invalid (non-numeric) timestamp header
- Expired timestamp (replay attack prevention)
- Boundary: exactly at MAX_TIMESTAMP_AGE_SECONDS
- Valid signature (happy path)
- Invalid signature (wrong secret)
- Empty signing secret
"""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.api.middleware.auth import (
    MAX_TIMESTAMP_AGE_SECONDS,
    SLACK_SIGNATURE_HEADER,
    SLACK_TIMESTAMP_HEADER,
    verify_slack_signature,
)


def _make_request(
    timestamp: str | None = None,
    signature: str | None = None,
    body: bytes = b"",
    secret: str = "test_secret",
) -> MagicMock:
    """Build a fake FastAPI Request with the given headers and body."""
    headers: dict[str, str] = {}
    if timestamp is not None:
        headers[SLACK_TIMESTAMP_HEADER] = timestamp
    if signature is not None:
        headers[SLACK_SIGNATURE_HEADER] = signature

    request = MagicMock()
    request.headers = headers
    request.body = AsyncMock(return_value=body)
    return request


def _valid_signature(secret: str, timestamp: str, body: bytes) -> str:
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"v0={digest}"


SIGNING_SECRET = "deadbeefdeadbeef"


@pytest.fixture(autouse=True)
def patch_secret(monkeypatch):
    secret_mock = MagicMock()
    secret_mock.get_secret_value.return_value = SIGNING_SECRET
    monkeypatch.setattr(
        "backend.api.middleware.auth.settings.SLACK_SIGNING_SECRET", secret_mock
    )


# ---------------------------------------------------------------------------
# Header validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_both_headers_raises_403():
    req = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403
    assert "Missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_missing_timestamp_raises_403():
    req = _make_request(signature="v0=abc")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_signature_raises_403():
    req = _make_request(timestamp=str(int(time.time())))
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_numeric_timestamp_raises_403():
    req = _make_request(timestamp="not-a-number", signature="v0=abc")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403
    assert "Invalid timestamp" in exc_info.value.detail


@pytest.mark.asyncio
async def test_expired_timestamp_raises_403():
    old_ts = str(int(time.time()) - MAX_TIMESTAMP_AGE_SECONDS - 1)
    req = _make_request(timestamp=old_ts, signature="v0=whatever")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403
    assert "replay" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_timestamp_at_boundary_raises_403():
    """Timestamp exactly one second past the boundary is rejected."""
    boundary_ts = str(time.time() - MAX_TIMESTAMP_AGE_SECONDS - 0.001)
    req = _make_request(timestamp=boundary_ts, signature="v0=whatever")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_timestamp_just_within_boundary_proceeds_to_sig_check():
    """Timestamp just inside the window reaches signature validation."""
    ts = str(time.time() - MAX_TIMESTAMP_AGE_SECONDS + 5)
    req = _make_request(timestamp=ts, signature="v0=badsig")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    # Must fail on signature, not timestamp
    assert exc_info.value.status_code == 403
    assert "Invalid Slack signature" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_signature_passes():
    body = b"payload=hello"
    ts = str(int(time.time()))
    sig = _valid_signature(SIGNING_SECRET, ts, body)
    req = _make_request(timestamp=ts, signature=sig, body=body)
    # Should not raise
    await verify_slack_signature(req)


@pytest.mark.asyncio
async def test_wrong_secret_raises_403():
    body = b"payload=hello"
    ts = str(int(time.time()))
    sig = _valid_signature("wrong_secret", ts, body)
    req = _make_request(timestamp=ts, signature=sig, body=body)
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403
    assert "Invalid Slack signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_tampered_body_raises_403():
    ts = str(int(time.time()))
    sig = _valid_signature(SIGNING_SECRET, ts, b"original body")
    req = _make_request(timestamp=ts, signature=sig, body=b"tampered body")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Empty signing secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_signing_secret_raises_403(monkeypatch):
    secret_mock = MagicMock()
    secret_mock.get_secret_value.return_value = ""
    monkeypatch.setattr(
        "backend.api.middleware.auth.settings.SLACK_SIGNING_SECRET", secret_mock
    )
    ts = str(int(time.time()))
    req = _make_request(timestamp=ts, signature="v0=anything")
    with pytest.raises(HTTPException) as exc_info:
        await verify_slack_signature(req)
    assert exc_info.value.status_code == 403
    assert "not configured" in exc_info.value.detail
