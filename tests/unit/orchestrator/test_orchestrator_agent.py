"""
Unit tests for OrchestratorAgent in Project AEGIS.

Redis is fully mocked - no running Redis server required.
"""

from datetime import UTC, datetime

import pytest

from src.models.alerts import PredictiveAlert
from src.models.dispatch import VehicleStatusSnapshot
from src.models.emergency import (
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    UnitsRequired,
)
from src.models.enums import AlertSeverity, FailureCategory, OperationalStatus, VehicleType
from src.models.events import VehicleRegistrationEvent
from src.models.telemetry import VehicleTelemetry
from src.models.vehicle import Location, VehicleRegistration
from src.orchestrator.agent import OrchestratorAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_location(lat: float = 19.43, lon: float = -99.13) -> Location:
    """Create a minimal Location."""
    return Location(
        latitude=lat,
        longitude=lon,
        timestamp=datetime(2026, 2, 10, 14, 0, 0, tzinfo=UTC),
    )


def _make_orchestrator() -> OrchestratorAgent:
    """Create an OrchestratorAgent with default config (no real Redis)."""
    return OrchestratorAgent(redis_host="localhost", fleet_id="fleet01")


def _make_telemetry_message(
    vehicle_id: str = "AMB-001",
    lat: float = 19.44,
    lon: float = -99.14,
    battery_voltage: float = 13.8,
    fuel_level: float = 75.0,
    vehicle_type: VehicleType = VehicleType.AMBULANCE,
) -> VehicleTelemetry:
    """Build a VehicleTelemetry model."""
    return VehicleTelemetry(
        vehicle_id=vehicle_id,
        vehicle_type=vehicle_type,
        timestamp=datetime.now(UTC),
        latitude=lat,
        longitude=lon,
        speed_kmh=0.0,
        odometer_km=1000.0,
        engine_temp_celsius=90.0,
        battery_voltage=battery_voltage,
        fuel_level_percent=fuel_level,
    )


def _make_emergency(
    ambulances: int = 1,
    lat: float = 19.43,
    lon: float = -99.13,
) -> Emergency:
    """Build a minimal Emergency."""
    return Emergency(
        emergency_type=EmergencyType.MEDICAL,
        severity=EmergencySeverity.HIGH,
        location=_make_location(lat, lon),
        description="Test emergency",
        units_required=UnitsRequired(ambulances=ambulances),
    )


@pytest.mark.unit
class TestVehicleRegistration:
    """Tests for explicit vehicle registration events."""

    @pytest.mark.asyncio
    async def test_registration_creates_snapshot(self) -> None:
        """Vehicle registration should pre-create fleet snapshot."""
        orch = _make_orchestrator()
        event = VehicleRegistrationEvent(
            payload=VehicleRegistration(
                vehicle_id="POL-123",
                vehicle_type=VehicleType.POLICE,
                fleet_id="fleet01",
                timestamp=datetime.now(UTC),
            )
        )
        await orch._handle_vehicle_registration(event)
        assert "POL-123" in orch.fleet
        assert orch.fleet["POL-123"].vehicle_type == VehicleType.POLICE


# ---------------------------------------------------------------------------
# OrchestratorAgent - fleet state management
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorFleetState:
    """Tests for fleet state updates via telemetry and heartbeat handling."""

    @pytest.mark.asyncio
    async def test_new_vehicle_registered_on_first_telemetry(self) -> None:
        """A new vehicle should be auto-registered when its telemetry arrives."""
        orch = _make_orchestrator()
        msg = _make_telemetry_message("AMB-001")
        await orch._handle_telemetry(msg)

        assert "AMB-001" in orch.fleet
        assert orch.fleet["AMB-001"].vehicle_type == VehicleType.AMBULANCE

    @pytest.mark.asyncio
    async def test_telemetry_updates_location(self) -> None:
        """Telemetry should update the vehicle's location in the snapshot."""
        orch = _make_orchestrator()
        msg = _make_telemetry_message("AMB-001", lat=19.50, lon=-99.20)
        await orch._handle_telemetry(msg)

        snap = orch.fleet["AMB-001"]
        assert snap.location is not None
        assert snap.location.latitude == pytest.approx(19.50)
        assert snap.location.longitude == pytest.approx(-99.20)

    @pytest.mark.asyncio
    async def test_telemetry_updates_battery_voltage(self) -> None:
        """Telemetry should update battery_voltage in the snapshot."""
        orch = _make_orchestrator()
        msg = _make_telemetry_message("AMB-001", battery_voltage=12.5)
        await orch._handle_telemetry(msg)

        assert orch.fleet["AMB-001"].battery_voltage == pytest.approx(12.5)

    @pytest.mark.asyncio
    async def test_telemetry_updates_fuel_level(self) -> None:
        """Telemetry should update fuel_level_percent in the snapshot."""
        orch = _make_orchestrator()
        msg = _make_telemetry_message("AMB-001", fuel_level=40.0)
        await orch._handle_telemetry(msg)

        assert orch.fleet["AMB-001"].fuel_level_percent == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_telemetry_updates_last_seen_at(self) -> None:
        """Telemetry should update last_seen_at timestamp."""
        orch = _make_orchestrator()
        msg = _make_telemetry_message("AMB-001")
        await orch._handle_telemetry(msg)

        assert orch.fleet["AMB-001"].last_seen_at is not None

    @pytest.mark.asyncio
    async def test_alert_marks_vehicle_has_active_alert(self) -> None:
        """Alert message should mark the vehicle as having an active alert."""
        orch = _make_orchestrator()
        await orch._handle_telemetry(_make_telemetry_message("AMB-001"))
        assert orch.fleet["AMB-001"].has_active_alert is False

        alert_msg = PredictiveAlert(
            vehicle_id="AMB-001",
            timestamp=datetime.now(UTC),
            severity=AlertSeverity.WARNING,
            category=FailureCategory.ELECTRICAL,
            component="alternator",
            failure_probability=0.8,
            confidence=0.9,
            predicted_failure_min_hours=1.0,
            predicted_failure_max_hours=5.0,
            predicted_failure_likely_hours=3.0,
            can_complete_current_mission=True,
            safe_to_operate=True,
            recommended_action="Inspect alternator",
        )
        await orch._handle_alert(alert_msg)
        assert orch.fleet["AMB-001"].has_active_alert is True

    @pytest.mark.asyncio
    async def test_invalid_message_is_ignored(self) -> None:
        """Malformed Redis message should be silently ignored."""
        orch = _make_orchestrator()
        raw = {"type": "message", "channel": "test", "data": "not-valid-json"}
        await orch._handle_raw_message(raw)  # Should not raise

    @pytest.mark.asyncio
    async def test_non_string_data_is_ignored(self) -> None:
        """Non-string data in raw message should be silently ignored."""
        orch = _make_orchestrator()
        raw = {"type": "message", "channel": "test", "data": None}
        await orch._handle_raw_message(raw)  # Should not raise


# ---------------------------------------------------------------------------
# OrchestratorAgent - emergency processing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorEmergencyProcessing:
    """Tests for emergency processing and dispatch (no Redis publish required)."""

    @pytest.fixture
    def orch_with_ambulance(self) -> OrchestratorAgent:
        """Orchestrator with one available ambulance pre-registered."""
        orch = _make_orchestrator()
        snap = VehicleStatusSnapshot(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
            operational_status=OperationalStatus.IDLE,
            location=_make_location(19.44, -99.14),
        )
        orch.fleet["AMB-001"] = snap
        # No real Redis - set _redis to None
        orch._redis = None
        return orch

    @pytest.mark.asyncio
    async def test_process_emergency_stores_it(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """process_emergency should store the emergency in the emergencies dict."""
        emergency = _make_emergency()
        await orch_with_ambulance.process_emergency(emergency)

        assert emergency.emergency_id in orch_with_ambulance.emergencies

    @pytest.mark.asyncio
    async def test_process_emergency_stores_dispatch(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """process_emergency should store the dispatch in the dispatches dict."""
        emergency = _make_emergency()
        dispatch = await orch_with_ambulance.process_emergency(emergency)

        assert emergency.emergency_id in orch_with_ambulance.dispatches
        assert (
            orch_with_ambulance.dispatches[emergency.emergency_id].dispatch_id
            == dispatch.dispatch_id
        )

    @pytest.mark.asyncio
    async def test_process_emergency_returns_dispatch(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """process_emergency should return a Dispatch with assigned units."""
        emergency = _make_emergency()
        dispatch = await orch_with_ambulance.process_emergency(emergency)

        assert len(dispatch.units) == 1
        assert dispatch.units[0].vehicle_id == "AMB-001"

    @pytest.mark.asyncio
    async def test_emergency_status_becomes_dispatched(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """Emergency status should be DISPATCHED after processing with available units."""
        emergency = _make_emergency()
        await orch_with_ambulance.process_emergency(emergency)

        stored = orch_with_ambulance.emergencies[emergency.emergency_id]
        assert stored.status == EmergencyStatus.DISPATCHED

    @pytest.mark.asyncio
    async def test_emergency_status_is_dispatching_when_no_units(self) -> None:
        """Emergency status should be DISPATCHING if no units were available."""
        orch = _make_orchestrator()
        orch._redis = None
        emergency = _make_emergency(ambulances=1)
        # Fleet is empty - no units available
        await orch.process_emergency(emergency)

        stored = orch.emergencies[emergency.emergency_id]
        assert stored.status == EmergencyStatus.DISPATCHING

    @pytest.mark.asyncio
    async def test_resolve_emergency_sets_resolved(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """resolve_emergency should mark the emergency as RESOLVED."""
        emergency = _make_emergency()
        await orch_with_ambulance.process_emergency(emergency)
        await orch_with_ambulance.resolve_emergency(emergency.emergency_id)

        stored = orch_with_ambulance.emergencies[emergency.emergency_id]
        assert stored.status == EmergencyStatus.RESOLVED
        assert stored.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_emergency_releases_vehicles(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """resolve_emergency should return vehicles to IDLE."""
        emergency = _make_emergency()
        await orch_with_ambulance.process_emergency(emergency)

        assert orch_with_ambulance.fleet["AMB-001"].operational_status == OperationalStatus.EN_ROUTE

        released = await orch_with_ambulance.resolve_emergency(emergency.emergency_id)

        assert "AMB-001" in released
        assert orch_with_ambulance.fleet["AMB-001"].operational_status == OperationalStatus.IDLE

    @pytest.mark.asyncio
    async def test_resolve_unknown_emergency_raises(
        self, orch_with_ambulance: OrchestratorAgent
    ) -> None:
        """Resolving an unknown emergency_id should raise KeyError."""
        with pytest.raises(KeyError):
            await orch_with_ambulance.resolve_emergency("nonexistent-id")


# ---------------------------------------------------------------------------
# Fleet summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorFleetSummary:
    """Tests for get_fleet_summary."""

    def test_empty_fleet_summary(self) -> None:
        """Empty fleet should report zeros."""
        orch = _make_orchestrator()
        summary = orch.get_fleet_summary()

        assert summary["total_vehicles"] == 0
        assert summary["available_vehicles"] == 0
        assert summary["active_emergencies"] == 0

    def test_summary_with_vehicles(self) -> None:
        """Summary should count total and available vehicles correctly."""
        orch = _make_orchestrator()
        orch.fleet["AMB-001"] = VehicleStatusSnapshot(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
            operational_status=OperationalStatus.IDLE,
        )
        orch.fleet["AMB-002"] = VehicleStatusSnapshot(
            vehicle_id="AMB-002",
            vehicle_type=VehicleType.AMBULANCE,
            operational_status=OperationalStatus.EN_ROUTE,
        )

        summary = orch.get_fleet_summary()

        assert summary["total_vehicles"] == 2
        assert summary["available_vehicles"] == 1

    def test_active_emergencies_count(self) -> None:
        """active_emergencies should exclude resolved/cancelled/dismissed emergencies."""
        orch = _make_orchestrator()
        e1 = _make_emergency()
        e2 = _make_emergency()
        e3 = _make_emergency()
        e2.status = EmergencyStatus.RESOLVED
        e3.status = EmergencyStatus.DISMISSED
        orch.emergencies[e1.emergency_id] = e1
        orch.emergencies[e2.emergency_id] = e2
        orch.emergencies[e3.emergency_id] = e3

        summary = orch.get_fleet_summary()
        assert summary["active_emergencies"] == 1
