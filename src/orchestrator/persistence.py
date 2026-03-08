"""Persistence adapters used by the orchestrator."""

from __future__ import annotations

import asyncio

import structlog

from src.core.persistence import AlertSink, TelemetrySink
from src.models.alerts import PredictiveAlert
from src.models.telemetry import VehicleTelemetry
from src.storage.database import db
from src.storage.repositories import AlertRepository, TelemetryRepository

logger = structlog.get_logger(__name__)


class DatabaseTelemetryPersister(TelemetrySink):
    """Batches telemetry records and flushes them to PostgreSQL."""

    def __init__(self, batch_size: int = 10) -> None:
        self._batch_size = batch_size
        self._buffer: list[tuple[VehicleTelemetry, str]] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, telemetry: VehicleTelemetry, vehicle_id: str) -> None:
        async with self._lock:
            self._buffer.append((telemetry, vehicle_id))
            should_flush = len(self._buffer) >= self._batch_size

        if should_flush:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if db.engine is None:
                self._buffer.clear()
                return
            batch, self._buffer = self._buffer, []

        if not batch:
            return

        try:
            async with db.session() as session:
                repo = TelemetryRepository(session)
                for telemetry, vehicle_id in batch:
                    await repo.save_telemetry(telemetry, vehicle_id)
            logger.debug("telemetry_batch_flushed", count=len(batch))
        except Exception as exc:
            logger.error("db_flush_telemetry_error", count=len(batch), error=str(exc))

    async def close(self) -> None:
        await self.flush()


class DatabaseAlertPersister(AlertSink):
    """Writes predictive alerts to PostgreSQL."""

    async def persist_alert(self, alert: PredictiveAlert, vehicle_id: str) -> None:
        if db.engine is None:
            return
        try:
            async with db.session() as session:
                repo = AlertRepository(session)
                await repo.save_alert(alert, vehicle_id)
        except Exception as exc:
            logger.error("db_persist_alert_error", vehicle_id=vehicle_id, error=str(exc))
