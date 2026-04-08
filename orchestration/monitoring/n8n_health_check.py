"""n8n health-check worker with circuit breaker.

States:
  CLOSED    — normal operation, requests pass through
  OPEN      — n8n is down; requests are blocked immediately
  HALF_OPEN — one probe request is allowed to test recovery

Usage (run as a background task):
    checker = N8nHealthChecker(settings)
    asyncio.create_task(checker.run())

    # In N8nPublisher or any caller:
    checker.guard()  # raises N8nUnavailableError if OPEN
"""

from __future__ import annotations

import asyncio
import enum
import time
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from backend.config.settings import Settings

logger = structlog.get_logger()


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class N8nUnavailableError(Exception):
    """Raised by guard() when the circuit is OPEN."""


class N8nHealthChecker:
    """Periodically pings n8n /healthz and maintains a circuit breaker.

    Args:
        health_url:       URL to GET for health (default: http://n8n:5678/healthz)
        interval:         seconds between checks when CLOSED
        failure_threshold: consecutive failures before opening the circuit
        recovery_timeout: seconds to wait in OPEN state before probing (HALF_OPEN)
        request_timeout:  seconds to wait for each health probe
    """

    def __init__(
        self,
        health_url: str,
        interval: float = 30.0,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        request_timeout: float = 5.0,
    ) -> None:
        self._url = health_url
        self._interval = interval
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._request_timeout = request_timeout

        self._state: CircuitState = CircuitState.CLOSED
        self._failures: int = 0
        self._opened_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state

    def guard(self) -> None:
        """Raise N8nUnavailableError if the circuit is OPEN.

        Call this before sending any request to n8n so it fails fast instead of
        hanging until httpx timeout.
        """
        if self._state is CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at
            raise N8nUnavailableError(
                f"n8n circuit is OPEN (opened {elapsed:.0f}s ago). "
                "Service appears to be unavailable."
            )

    async def run(self) -> None:
        """Background loop — run with asyncio.create_task()."""
        logger.info("n8n_health_checker_started", url=self._url)
        while True:
            await self._tick()
            sleep_secs = self._sleep_interval()
            await asyncio.sleep(sleep_secs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        if self._state is CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self._recovery_timeout:
                return  # still cooling down
            self._transition(CircuitState.HALF_OPEN)

        ok = await self._probe()
        if ok:
            self._on_success()
        else:
            self._on_failure()

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(self._url, timeout=self._request_timeout)
            if resp.status_code < 500:
                return True
            logger.warning("n8n_health_check_bad_status", status=resp.status_code)
            return False
        except Exception as exc:
            logger.warning("n8n_health_check_error", error=str(exc))
            return False

    def _on_success(self) -> None:
        if self._state is not CircuitState.CLOSED:
            logger.info("n8n_circuit_closed", previous=self._state)
        self._failures = 0
        self._state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        logger.warning(
            "n8n_health_check_failure", failures=self._failures, state=self._state
        )

        if self._state is CircuitState.HALF_OPEN:
            # Probe failed — stay/re-open
            self._transition(CircuitState.OPEN)
        elif self._failures >= self._failure_threshold:
            self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        logger.error(
            "n8n_circuit_state_changed",
            old=self._state,
            new=new_state,
            failures=self._failures,
        )
        self._state = new_state
        if new_state is CircuitState.OPEN:
            self._opened_at = time.monotonic()

    def _sleep_interval(self) -> float:
        if self._state is CircuitState.OPEN:
            remaining = self._recovery_timeout - (time.monotonic() - self._opened_at)
            return max(remaining, 1.0)
        return self._interval


def build_health_checker(settings: "Settings") -> N8nHealthChecker:
    """Factory that reads configuration from Settings."""
    return N8nHealthChecker(
        health_url=settings.N8N_HEALTH_URL,
        interval=settings.N8N_HEALTH_INTERVAL,
        failure_threshold=settings.N8N_HEALTH_FAILURE_THRESHOLD,
        recovery_timeout=settings.N8N_HEALTH_RECOVERY_TIMEOUT,
        request_timeout=settings.N8N_HEALTH_REQUEST_TIMEOUT,
    )
