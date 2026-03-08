"""In-memory message bus used by end-to-end tests."""

from __future__ import annotations

import asyncio
import fnmatch
from collections.abc import AsyncIterator

from src.core.messaging import BusMessage, MessageBus


class InMemoryMessageBus(MessageBus):
    """Simple fan-out pub/sub bus with wildcard pattern subscriptions."""

    def __init__(self) -> None:
        self._connected = False
        self._subscribers: list[tuple[list[str], asyncio.Queue[BusMessage]]] = []
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False
        async with self._lock:
            for _, queue in self._subscribers:
                queue.put_nowait(BusMessage(channel="", data=""))
            self._subscribers.clear()

    async def publish(self, channel: str, payload: str) -> None:
        if not self._connected:
            raise RuntimeError("In-memory bus not connected")

        async with self._lock:
            for patterns, queue in self._subscribers:
                if any(fnmatch.fnmatch(channel, pat) for pat in patterns):
                    queue.put_nowait(BusMessage(channel=channel, data=payload))

    def subscribe_patterns(self, *patterns: str) -> AsyncIterator[BusMessage]:
        return self._subscribe_patterns_impl(*patterns)

    async def _subscribe_patterns_impl(self, *patterns: str) -> AsyncIterator[BusMessage]:
        if not self._connected:
            raise RuntimeError("In-memory bus not connected")

        queue: asyncio.Queue[BusMessage] = asyncio.Queue()
        subscriber = (list(patterns), queue)
        async with self._lock:
            self._subscribers.append(subscriber)

        try:
            while True:
                message = await queue.get()
                if not message.channel and not message.data and not self._connected:
                    break
                yield message
        finally:
            async with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)
