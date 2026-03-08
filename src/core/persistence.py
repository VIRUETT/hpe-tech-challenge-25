"""Persistence contracts for orchestrator side effects."""

from __future__ import annotations

from typing import Protocol

from src.models.alerts import PredictiveAlert
from src.models.telemetry import VehicleTelemetry


class TelemetrySink(Protocol):
    """Consumes telemetry records for persistence or analytics."""

    async def enqueue(self, telemetry: VehicleTelemetry, vehicle_id: str) -> None:
        """Accept one telemetry record for asynchronous persistence."""

    async def flush(self) -> None:
        """Flush all pending records."""

    async def close(self) -> None:
        """Release resources and flush pending data."""


class AlertSink(Protocol):
    """Consumes alerts for persistence."""

    async def persist_alert(self, alert: PredictiveAlert, vehicle_id: str) -> None:
        """Persist one alert entry."""
