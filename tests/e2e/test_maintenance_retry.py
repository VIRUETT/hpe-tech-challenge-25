"""End-to-end maintenance and dispatch retry scenarios."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.core.time import FastForwardClock
from src.infrastructure.in_memory_bus import InMemoryMessageBus
from src.models.emergency import Emergency, EmergencySeverity, EmergencyType, UnitsRequired
from src.models.enums import OperationalStatus, VehicleType
from src.models.vehicle import Location
from src.orchestrator.agent import OrchestratorAgent
from src.vehicle_agent.agent import VehicleAgent
from src.vehicle_agent.config import AgentConfig


class _NoopTelemetrySink:
    async def enqueue(self, telemetry: Any, vehicle_id: str) -> None:
        return

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


class _NoopAlertSink:
    async def persist_alert(self, alert: Any, vehicle_id: str) -> None:
        return


async def _advance_ticks(clock: FastForwardClock, ticks: int) -> None:
    for _ in range(ticks):
        clock.advance(1.0)
        await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool], max_attempts: int = 80) -> None:
    for _ in range(max_attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("Condition not reached within max attempts")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_maintenance_completion_retries_waiting_dispatch() -> None:
    """Repair completion should trigger retry and dispatch waiting emergencies."""
    bus = InMemoryMessageBus()
    clock = FastForwardClock(start_at=datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC))

    orchestrator = OrchestratorAgent(
        fleet_id="fleet01",
        message_bus=bus,
        clock=clock,
        telemetry_sink=_NoopTelemetrySink(),
        alert_sink=_NoopAlertSink(),
    )

    amb1 = VehicleAgent(
        AgentConfig(
            vehicle_id="AMB-101",
            vehicle_type=VehicleType.AMBULANCE,
            fleet_id="fleet01",
            telemetry_frequency_hz=1.0,
            initial_latitude=37.7749,
            initial_longitude=-122.4194,
        ),
        message_bus=bus,
        clock=clock,
    )
    orch_task = asyncio.create_task(orchestrator.run())
    amb1_task = asyncio.create_task(amb1.run())

    try:
        await _advance_ticks(clock, 3)
        await _wait_until(lambda: "AMB-101" in orchestrator.fleet)

        emergency_a = Emergency(
            emergency_type=EmergencyType.MEDICAL,
            severity=EmergencySeverity.HIGH,
            location=Location(latitude=37.7749, longitude=-122.4194, timestamp=clock.now()),
            description="first assignment",
            units_required=UnitsRequired(ambulances=1),
        )
        await orchestrator.process_emergency(emergency_a)

        await _wait_until(lambda: amb1.operational_status == OperationalStatus.EN_ROUTE)
        # Make the vehicle unavailable for a second emergency while under repair.
        await amb1._enter_maintenance()
        snap = orchestrator.fleet["AMB-101"]
        snap.operational_status = OperationalStatus.MAINTENANCE
        snap.has_active_alert = True

        emergency_b = Emergency(
            emergency_type=EmergencyType.MEDICAL,
            severity=EmergencySeverity.HIGH,
            location=Location(latitude=37.7759, longitude=-122.4184, timestamp=clock.now()),
            description="waiting assignment",
            units_required=UnitsRequired(ambulances=1),
        )
        dispatch_b = await orchestrator.process_emergency(emergency_b)
        assert dispatch_b.units == []
        assert emergency_b.status.value == "dispatching"

        amb1._repair_duration_seconds = 1.0
        amb1._repair_started_at = clock.now() - timedelta(seconds=2)
        assert amb1.operational_status == OperationalStatus.MAINTENANCE

        # Fast-forward through repair window; clear event should trigger retry.
        await _advance_ticks(clock, 3)
        await _wait_until(lambda: emergency_b.status.value == "dispatched")
        await _wait_until(lambda: amb1.current_emergency_id == emergency_b.emergency_id)
        await _wait_until(lambda: amb1.operational_status == OperationalStatus.EN_ROUTE)
    finally:
        amb1.running = False
        orchestrator.running = False
        await _advance_ticks(clock, 1)
        await bus.close()
        await asyncio.wait_for(orch_task, timeout=1.0)
        await asyncio.wait_for(amb1_task, timeout=1.0)
