"""
Unit tests for the DispatchEngine in Project AEGIS.

All tests use in-memory fleet state - no Redis required.
"""

from datetime import UTC, datetime

import pytest

from src.models.dispatch import VehicleStatusSnapshot
from src.models.emergency import Emergency, EmergencySeverity, EmergencyType, UnitsRequired
from src.models.enums import OperationalStatus, VehicleType
from src.models.vehicle import Location
from src.orchestrator.dispatch_engine import DispatchEngine, _haversine_km

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_location(lat: float, lon: float) -> Location:
    """Create a Location with minimal fields."""
    return Location(
        latitude=lat,
        longitude=lon,
        timestamp=datetime(2026, 2, 10, 14, 0, 0, tzinfo=UTC),
    )


def _make_snapshot(
    vehicle_id: str,
    vehicle_type: VehicleType,
    lat: float,
    lon: float,
    status: OperationalStatus = OperationalStatus.IDLE,
    has_alert: bool = False,
) -> VehicleStatusSnapshot:
    """Build a VehicleStatusSnapshot with a known location."""
    return VehicleStatusSnapshot(
        vehicle_id=vehicle_id,
        vehicle_type=vehicle_type,
        operational_status=status,
        location=_make_location(lat, lon),
        has_active_alert=has_alert,
    )


def _make_emergency(
    lat: float,
    lon: float,
    emergency_type: EmergencyType = EmergencyType.MEDICAL,
    ambulances: int = 1,
    fire_trucks: int = 0,
    police: int = 0,
) -> Emergency:
    """Build an Emergency at the given location."""
    return Emergency(
        emergency_type=emergency_type,
        severity=EmergencySeverity.HIGH,
        location=_make_location(lat, lon),
        description="Test emergency",
        units_required=UnitsRequired(ambulances=ambulances, fire_trucks=fire_trucks, police=police),
    )


@pytest.fixture
def simple_fleet() -> dict[str, VehicleStatusSnapshot]:
    """Fleet with 2 ambulances at different distances from CDMX center (19.43, -99.13)."""
    return {
        "AMB-001": _make_snapshot("AMB-001", VehicleType.AMBULANCE, 19.44, -99.14),  # ~1.5 km
        "AMB-002": _make_snapshot("AMB-002", VehicleType.AMBULANCE, 19.50, -99.20),  # ~10 km
    }


@pytest.fixture
def mixed_fleet() -> dict[str, VehicleStatusSnapshot]:
    """Fleet with ambulances, fire trucks, and police."""
    return {
        "AMB-001": _make_snapshot("AMB-001", VehicleType.AMBULANCE, 19.44, -99.14),
        "AMB-002": _make_snapshot("AMB-002", VehicleType.AMBULANCE, 19.50, -99.20),
        "FIRE-001": _make_snapshot("FIRE-001", VehicleType.FIRE_TRUCK, 19.43, -99.13),
        "FIRE-002": _make_snapshot("FIRE-002", VehicleType.FIRE_TRUCK, 19.40, -99.10),
        "POL-001": _make_snapshot("POL-001", VehicleType.POLICE, 19.45, -99.15),
    }


# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHaversine:
    """Tests for the Haversine distance helper."""

    def test_same_point_is_zero(self) -> None:
        """Distance from a point to itself should be 0."""
        loc = _make_location(19.43, -99.13)
        assert _haversine_km(loc, loc) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance(self) -> None:
        """Mexico City to Guadalajara is roughly 460-470 km."""
        cdmx = _make_location(19.4326, -99.1332)
        gdl = _make_location(20.6597, -103.3496)
        dist = _haversine_km(cdmx, gdl)
        assert 450 < dist < 490

    def test_symmetry(self) -> None:
        """Distance A->B should equal B->A."""
        a = _make_location(19.43, -99.13)
        b = _make_location(19.50, -99.20)
        assert _haversine_km(a, b) == pytest.approx(_haversine_km(b, a), rel=1e-9)

    def test_distance_is_positive(self) -> None:
        """Distance between different points must be positive."""
        a = _make_location(19.43, -99.13)
        b = _make_location(19.44, -99.14)
        assert _haversine_km(a, b) > 0


# ---------------------------------------------------------------------------
# DispatchEngine
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDispatchEngine:
    """Tests for DispatchEngine unit selection logic."""

    def test_selects_nearest_ambulance(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """DispatchEngine should select the nearest ambulance."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=1)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 1
        assert dispatch.units[0].vehicle_id == "AMB-001"

    def test_dispatch_has_correct_emergency_id(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Dispatch emergency_id should match the processed emergency."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13)
        dispatch = engine.select_units(emergency)

        assert dispatch.emergency_id == emergency.emergency_id

    def test_selected_vehicle_marked_en_route(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Dispatched vehicle should be marked EN_ROUTE in fleet state."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13)
        dispatch = engine.select_units(emergency)

        vehicle_id = dispatch.units[0].vehicle_id
        assert simple_fleet[vehicle_id].operational_status == OperationalStatus.EN_ROUTE

    def test_selected_vehicle_has_emergency_id(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Dispatched vehicle snapshot should store the emergency_id."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13)
        dispatch = engine.select_units(emergency)

        vehicle_id = dispatch.units[0].vehicle_id
        assert simple_fleet[vehicle_id].current_emergency_id == emergency.emergency_id

    def test_selects_two_ambulances(self, simple_fleet: dict[str, VehicleStatusSnapshot]) -> None:
        """Should select 2 ambulances when requested."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=2)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 2
        ids = {u.vehicle_id for u in dispatch.units}
        assert "AMB-001" in ids
        assert "AMB-002" in ids

    def test_partial_dispatch_when_insufficient(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Should dispatch as many as available when fewer than required."""
        engine = DispatchEngine(simple_fleet)
        # Request 3 but only 2 exist
        emergency = _make_emergency(19.43, -99.13, ambulances=3)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 2  # Only 2 available

    def test_no_units_dispatched_when_all_unavailable(self) -> None:
        """If all vehicles are en_route, dispatch should have 0 units."""
        fleet = {
            "AMB-001": _make_snapshot(
                "AMB-001",
                VehicleType.AMBULANCE,
                19.44,
                -99.14,
                status=OperationalStatus.EN_ROUTE,
            ),
        }
        engine = DispatchEngine(fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=1)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 0

    def test_skips_vehicles_with_active_alert(self) -> None:
        """Vehicles with active alerts should not be dispatched."""
        fleet = {
            "AMB-001": _make_snapshot(
                "AMB-001", VehicleType.AMBULANCE, 19.43, -99.13, has_alert=True
            ),
            "AMB-002": _make_snapshot("AMB-002", VehicleType.AMBULANCE, 19.50, -99.20),
        }
        engine = DispatchEngine(fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=1)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 1
        assert dispatch.units[0].vehicle_id == "AMB-002"

    def test_dispatches_multiple_types(self, mixed_fleet: dict[str, VehicleStatusSnapshot]) -> None:
        """Should dispatch correct types for multi-type emergency."""
        engine = DispatchEngine(mixed_fleet)
        emergency = _make_emergency(
            19.43,
            -99.13,
            emergency_type=EmergencyType.FIRE,
            ambulances=1,
            fire_trucks=1,
        )
        dispatch = engine.select_units(emergency)

        types = {u.vehicle_type for u in dispatch.units}
        assert VehicleType.AMBULANCE in types
        assert VehicleType.FIRE_TRUCK in types
        assert len(dispatch.units) == 2

    def test_release_units_sets_idle(self) -> None:
        """release_units should set vehicles back to IDLE and clear emergency_id."""
        fleet = {
            "AMB-001": _make_snapshot("AMB-001", VehicleType.AMBULANCE, 19.43, -99.13),
        }
        engine = DispatchEngine(fleet)
        emergency = _make_emergency(19.43, -99.13)
        engine.select_units(emergency)

        assert fleet["AMB-001"].operational_status == OperationalStatus.EN_ROUTE

        released = engine.release_units(emergency.emergency_id)

        assert "AMB-001" in released
        assert fleet["AMB-001"].operational_status == OperationalStatus.IDLE
        assert fleet["AMB-001"].current_emergency_id is None

    def test_release_units_returns_correct_ids(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """release_units should return the list of released vehicle IDs."""
        engine = DispatchEngine(simple_fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=2)
        dispatch = engine.select_units(emergency)

        released = engine.release_units(emergency.emergency_id)
        assert set(released) == set(dispatch.vehicle_ids)

    def test_available_count_reflects_fleet(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """available_count should reflect current availability."""
        engine = DispatchEngine(simple_fleet)
        counts = engine.available_count

        assert counts.get("ambulance", 0) == 2

    def test_available_count_decreases_after_dispatch(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """available_count should decrease after dispatch."""
        engine = DispatchEngine(simple_fleet)
        engine.select_units(_make_emergency(19.43, -99.13, ambulances=1))

        counts = engine.available_count
        assert counts.get("ambulance", 0) == 1  # One dispatched, one still idle

    def test_skips_vehicles_without_location(self) -> None:
        """Vehicles without a known location cannot be dispatched."""
        fleet: dict[str, VehicleStatusSnapshot] = {
            "AMB-001": VehicleStatusSnapshot(
                vehicle_id="AMB-001",
                vehicle_type=VehicleType.AMBULANCE,
                operational_status=OperationalStatus.IDLE,
                location=None,
            ),
            "AMB-002": _make_snapshot("AMB-002", VehicleType.AMBULANCE, 19.50, -99.20),
        }
        engine = DispatchEngine(fleet)
        emergency = _make_emergency(19.43, -99.13, ambulances=1)
        dispatch = engine.select_units(emergency)

        assert len(dispatch.units) == 1
        assert dispatch.units[0].vehicle_id == "AMB-002"

    def test_selection_criteria_is_nearest_available(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Dispatch selection_criteria should document the algorithm used."""
        engine = DispatchEngine(simple_fleet)
        dispatch = engine.select_units(_make_emergency(19.43, -99.13))
        assert dispatch.selection_criteria == "nearest_available"

    def test_dispatched_unit_has_role_and_eta(
        self, simple_fleet: dict[str, VehicleStatusSnapshot]
    ) -> None:
        """Dispatched units should include role assignment and ETA metadata."""
        engine = DispatchEngine(simple_fleet)
        dispatch = engine.select_units(_make_emergency(19.43, -99.13))

        unit = dispatch.units[0]
        assert unit.role is not None
        assert unit.estimated_eta_minutes is not None
        assert unit.estimated_eta_minutes >= 1.0
        assert unit.estimated_arrival_at is not None
