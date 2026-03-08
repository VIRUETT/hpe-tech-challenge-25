"""Simulation time abstractions.

Provides a small clock interface so production code can run in real time while
tests can fast-forward deterministically.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Abstract time source used by agents and services."""

    def now(self) -> datetime:
        """Return current timestamp in UTC."""

    async def sleep(self, seconds: float) -> None:
        """Suspend execution for ``seconds`` of clock time."""

    def monotonic(self) -> float:
        """Return monotonic clock value in seconds."""


class RealClock:
    """Clock implementation backed by the system event loop."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def monotonic(self) -> float:
        return asyncio.get_running_loop().time()


class FastForwardClock:
    """Deterministic clock for tests with manual time advancement."""

    def __init__(self, start_at: datetime | None = None) -> None:
        self._now = start_at or datetime.now(UTC)
        self._mono = 0.0
        self._waiters: list[tuple[float, asyncio.Event]] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        target = self._mono + seconds
        event = asyncio.Event()
        self._waiters.append((target, event))
        await event.wait()

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        """Advance clock time and wake sleepers whose target is reached."""
        if seconds < 0:
            raise ValueError("Cannot advance clock by negative duration")
        self._mono += seconds
        self._now = self._now + timedelta(seconds=seconds)

        pending: list[tuple[float, asyncio.Event]] = []
        for target, event in self._waiters:
            if target <= self._mono:
                event.set()
            else:
                pending.append((target, event))
        self._waiters = pending
