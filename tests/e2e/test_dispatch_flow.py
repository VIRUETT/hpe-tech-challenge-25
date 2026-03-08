"""End-to-end tests for orchestrator/vehicle interaction using in-memory infrastructure."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from src.core.time import FastForwardClock
from src.infrastructure.in_memory_bus import InMemoryMessageBus
from src.models.emergency import Emergency, EmergencySeverity, EmergencyType, UnitsRequired
from src.models.enums import OperationalStatus, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.models.vehicle import Location
from src.orchestrator.agent import OrchestratorAgent
from src.vehicle_agent.agent import VehicleAgent
from src.vehicle_agent.config import AgentConfig


class InMemoryTelemetrySink:
    """Simple telemetry sink used for test assertions."""

    def __init__(self) -> None:
        self.records: list[tuple[str, datetime]] = []

    async def enqueue(self, telemetry: VehicleTelemetry, vehicle_id: str) -> None:
        self.records.append((vehicle_id, telemetry.timestamp))

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


class InMemoryAlertSink:
    """Simple alert sink used for test assertions."""

    def __init__(self) -> None:
        self.alerts: list[str] = []

    async def persist_alert(self, alert: Any, vehicle_id: str) -> None:
        self.alerts.append(vehicle_id)


async def _advance_ticks(clock: FastForwardClock, ticks: int) -> None:
    """Advance simulation time and yield to pending async tasks."""
    for _ in range(ticks):
        clock.advance(1.0)
        await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool], max_attempts: int = 50) -> None:
    """Wait until a condition becomes true or fail."""
    for _ in range(max_attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("Condition not reached within max attempts")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_lifecycle_with_fast_forward_clock() -> None:
    """Vehicle receives dispatch, reaches scene, and returns to IDLE on resolve."""
    bus = InMemoryMessageBus()
    clock = FastForwardClock(start_at=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC))
    telemetry_sink = InMemoryTelemetrySink()
    alert_sink = InMemoryAlertSink()

    orchestrator = OrchestratorAgent(
        fleet_id="fleet01",
        message_bus=bus,
        clock=clock,
        telemetry_sink=telemetry_sink,
        alert_sink=alert_sink,
    )
    vehicle = VehicleAgent(
        AgentConfig(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
            fleet_id="fleet01",
            telemetry_frequency_hz=1.0,
            initial_latitude=37.7749,
            initial_longitude=-122.4194,
        ),
        message_bus=bus,
        clock=clock,
    )

    orchestrator_task = asyncio.create_task(orchestrator.run())
    vehicle_task = asyncio.create_task(vehicle.run())

    try:
        await _advance_ticks(clock, 2)
        await _wait_until(lambda: "AMB-001" in orchestrator.fleet)

        emergency = Emergency(
            emergency_type=EmergencyType.MEDICAL,
            severity=EmergencySeverity.HIGH,
            location=Location(
                latitude=37.7749,
                longitude=-122.4194,
                timestamp=clock.now(),
            ),
            description="E2E dispatch test",
            units_required=UnitsRequired(ambulances=1),
        )
        await orchestrator.process_emergency(emergency)

        await _wait_until(lambda: vehicle.operational_status == OperationalStatus.EN_ROUTE)
        await _advance_ticks(clock, 2)
        await _wait_until(lambda: vehicle.operational_status == OperationalStatus.ON_SCENE)

        await orchestrator.resolve_emergency(emergency.emergency_id)
        await _wait_until(lambda: vehicle.operational_status == OperationalStatus.IDLE)
        assert vehicle.current_emergency_id is None
    finally:
        vehicle.running = False
        orchestrator.running = False
        await _advance_ticks(clock, 1)
        await bus.close()
        await asyncio.wait_for(orchestrator_task, timeout=1.0)
        await asyncio.wait_for(vehicle_task, timeout=1.0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fast_forward_advances_uptime_and_persists_telemetry() -> None:
    """Fast-forward simulation should produce telemetry without wall-clock sleeps."""
    bus = InMemoryMessageBus()
    clock = FastForwardClock(start_at=datetime(2026, 3, 1, 10, 30, 0, tzinfo=UTC))
    telemetry_sink = InMemoryTelemetrySink()

    orchestrator = OrchestratorAgent(
        fleet_id="fleet01",
        message_bus=bus,
        clock=clock,
        telemetry_sink=telemetry_sink,
        alert_sink=InMemoryAlertSink(),
    )
    vehicle = VehicleAgent(
        AgentConfig(
            vehicle_id="AMB-002",
            vehicle_type=VehicleType.AMBULANCE,
            fleet_id="fleet01",
            telemetry_frequency_hz=1.0,
        ),
        message_bus=bus,
        clock=clock,
    )

    orchestrator_task = asyncio.create_task(orchestrator.run())
    vehicle_task = asyncio.create_task(vehicle.run())

    try:
        await _advance_ticks(clock, 6)
        await _wait_until(lambda: len(telemetry_sink.records) >= 3)

        assert vehicle.uptime_seconds >= 5.0
        assert any(vehicle_id == "AMB-002" for vehicle_id, _ in telemetry_sink.records)
    finally:
        vehicle.running = False
        orchestrator.running = False
        await _advance_ticks(clock, 1)
        await bus.close()
        await asyncio.wait_for(orchestrator_task, timeout=1.0)
        await asyncio.wait_for(vehicle_task, timeout=1.0)
