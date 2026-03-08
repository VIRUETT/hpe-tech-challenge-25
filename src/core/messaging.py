"""Messaging abstractions for inter-agent communication."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class BusMessage:
    """Normalized message delivered by a message bus."""

    channel: str
    data: str


class MessageBus(Protocol):
    """Abstract pub/sub message bus contract."""

    async def connect(self) -> None:
        """Establish bus connection or initialize in-memory resources."""

    async def close(self) -> None:
        """Close bus resources."""

    async def publish(self, channel: str, payload: str) -> None:
        """Publish a message payload to ``channel``."""

    def subscribe_patterns(self, *patterns: str) -> AsyncIterator[BusMessage]:
        """Yield messages matching one or more wildcard channel patterns."""
