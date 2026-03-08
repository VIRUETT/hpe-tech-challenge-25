"""Redis-backed implementation of the MessageBus contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import redis.asyncio as redis

from src.core.messaging import BusMessage, MessageBus


class RedisMessageBus(MessageBus):
    """Message bus adapter over Redis pub/sub."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str | None,
        db: int,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._db = db
        self._redis: redis.Redis | None = None

    @property
    def redis(self) -> redis.Redis | None:
        """Expose underlying redis client when low-level access is required."""
        return self._redis

    async def connect(self) -> None:
        if self._redis is not None:
            return
        self._redis = redis.Redis(
            host=self._host,
            port=self._port,
            password=self._password,
            db=self._db,
            decode_responses=True,
        )
        await self._redis.ping()

    async def close(self) -> None:
        if self._redis is None:
            return
        if hasattr(self._redis, "aclose"):
            await self._redis.aclose()
        else:
            await self._redis.close()
        self._redis = None

    async def publish(self, channel: str, payload: str) -> None:
        if self._redis is None:
            raise RuntimeError("Redis bus not connected")
        await self._redis.publish(channel, payload)

    def subscribe_patterns(self, *patterns: str) -> AsyncIterator[BusMessage]:
        return self._subscribe_patterns_impl(*patterns)

    async def _subscribe_patterns_impl(self, *patterns: str) -> AsyncIterator[BusMessage]:
        if self._redis is None:
            raise RuntimeError("Redis bus not connected")

        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(*patterns)
        try:
            async for raw in pubsub.listen():
                if raw.get("type") not in ("message", "pmessage"):
                    continue
                data = raw.get("data")
                if not data or not isinstance(data, str):
                    continue
                channel = raw.get("channel", "") or raw.get("pattern", "") or ""
                yield BusMessage(channel=channel, data=data)
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.punsubscribe()
            await pubsub.close()
