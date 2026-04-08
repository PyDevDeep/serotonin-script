"""Slack request signature verification middleware."""

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from backend.config.settings import settings

SLACK_SIGNATURE_HEADER = "X-Slack-Signature"
SLACK_TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"
MAX_TIMESTAMP_AGE_SECONDS = 300


async def verify_slack_signature(request: Request) -> None:
    """Verify that a request originates from Slack using HMAC-SHA256 signature.

    Args:
        request: The incoming FastAPI request.

    Raises:
        HTTPException: 403 if the signature is missing, expired, or invalid.
    """
    signing_secret = settings.SLACK_SIGNING_SECRET.get_secret_value()
    if not signing_secret:
        raise HTTPException(
            status_code=403, detail="Slack signing secret not configured"
        )

    timestamp = request.headers.get(SLACK_TIMESTAMP_HEADER)
    slack_signature = request.headers.get(SLACK_SIGNATURE_HEADER)

    if not timestamp or not slack_signature:
        raise HTTPException(status_code=403, detail="Missing Slack signature headers")

    try:
        request_age = abs(time.time() - float(timestamp))
    except ValueError as err:
        raise HTTPException(status_code=403, detail="Invalid timestamp header") from err

    if request_age > MAX_TIMESTAMP_AGE_SECONDS:
        raise HTTPException(
            status_code=403, detail="Request timestamp too old (replay attack)"
        )

    body = await request.body()
    base_string = f"v0:{timestamp}:{body.decode('utf-8')}"

    expected = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected, slack_signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")
