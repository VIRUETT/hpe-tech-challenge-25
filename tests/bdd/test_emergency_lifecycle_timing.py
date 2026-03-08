"""BDD step definitions for emergency lifecycle timing behavior."""

from datetime import UTC, datetime

import pytest
from pytest_bdd import given, scenario, then, when

from src.core.time import FastForwardClock
from src.models.dispatch import VehicleStatusSnapshot
from src.models.emergency import (
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    UnitsRequired,
)
from src.models.enums import OperationalStatus, VehicleType
from src.models.vehicle import Location
from src.orchestrator.emergency_service import EmergencyService

FEATURE = "../features/emergency_lifecycle_timing.feature"


@scenario(FEATURE, "Emergency enters in-progress when first unit arrives")
def test_emergency_enters_in_progress() -> None:
    """An assigned unit arriving marks the emergency as IN_PROGRESS."""


@scenario(FEATURE, "In-progress emergency reaches planned auto-resolution window")
def test_emergency_reaches_planned_resolution_window() -> None:
    """IN_PROGRESS incidents become auto-resolvable after planned duration."""


@scenario(FEATURE, "Dispatched emergency is dismissed after stall timeout")
def test_emergency_dismissed_after_dispatched_stall() -> None:
    """DISPATCHED incidents are dismissed when stalled too long."""


class EmergencyTimingContext:
    """Shared scenario context for emergency timing BDD tests."""

    def __init__(self) -> None:
        self.clock = FastForwardClock(start_at=datetime(2026, 3, 3, 9, 0, 0, tzinfo=UTC))
        self.fleet: dict[str, VehicleStatusSnapshot] = {
            "AMB-001": VehicleStatusSnapshot(
                vehicle_id="AMB-001",
                vehicle_type=VehicleType.AMBULANCE,
                operational_status=OperationalStatus.IDLE,
                location=Location(
                    latitude=37.7749,
                    longitude=-122.4194,
                    timestamp=datetime(2026, 3, 3, 9, 0, 0, tzinfo=UTC),
                ),
            )
        }
        self.service = EmergencyService(self.fleet, clock=self.clock)
        self.emergency: Emergency | None = None
        self.auto_resolve: list[Emergency] = []
        self.auto_dismiss: list[Emergency] = []


@pytest.fixture
def ctx() -> EmergencyTimingContext:
    """Provide isolated scenario context."""
    return EmergencyTimingContext()


@given("a fast-forward emergency service with one ambulance")
def given_service_with_fleet(ctx: EmergencyTimingContext) -> None:
    """Ensure BDD context starts from a deterministic emergency service."""
    assert "AMB-001" in ctx.fleet


@given("a new medical emergency that needs 1 ambulance")
def given_new_medical_emergency(ctx: EmergencyTimingContext) -> None:
    """Create a deterministic medical emergency using simulation time."""
    ctx.emergency = Emergency(
        emergency_type=EmergencyType.MEDICAL,
        severity=EmergencySeverity.HIGH,
        location=Location(latitude=37.7750, longitude=-122.4195, timestamp=ctx.clock.now()),
        description="BDD emergency",
        units_required=UnitsRequired(ambulances=1),
        created_at=ctx.clock.now(),
    )


@when("the emergency is dispatched")
def when_emergency_dispatched(ctx: EmergencyTimingContext) -> None:
    """Process emergency and ensure at least one unit is assigned."""
    assert ctx.emergency is not None
    dispatch = ctx.service.process_emergency(ctx.emergency)
    assert dispatch.units


@when("the first assigned unit arrives on scene")
def when_first_unit_arrives(ctx: EmergencyTimingContext) -> None:
    """Mark the emergency as in progress after first arrival."""
    assert ctx.emergency is not None
    changed = ctx.service.mark_emergency_in_progress(ctx.emergency.emergency_id)
    assert changed is True


@when("simulation time advances to the planned resolution window")
def when_time_advances_to_planned_window(ctx: EmergencyTimingContext) -> None:
    """Advance simulated time to expected resolution horizon."""
    assert ctx.emergency is not None
    eta = ctx.service.expected_resolution_eta(ctx.emergency.emergency_id)
    assert eta is not None
    delta_seconds = int((eta - ctx.clock.now()).total_seconds())
    if delta_seconds > 0:
        ctx.clock.advance(float(delta_seconds))
    _cancel, ctx.auto_resolve, ctx.auto_dismiss = ctx.service.evaluate_stale_emergencies()


@when("simulation time advances by 25 minutes")
def when_time_advances_by_25_minutes(ctx: EmergencyTimingContext) -> None:
    """Advance simulated clock to dispatched stall timeout threshold."""
    ctx.clock.advance(25.0 * 60.0)
    _cancel, ctx.auto_resolve, ctx.auto_dismiss = ctx.service.evaluate_stale_emergencies()


@then("the emergency status should be in_progress")
def then_status_is_in_progress(ctx: EmergencyTimingContext) -> None:
    """Emergency should have transitioned to in-progress."""
    assert ctx.emergency is not None
    assert ctx.emergency.status == EmergencyStatus.IN_PROGRESS


@then("the emergency should be eligible for auto-resolution")
def then_eligible_for_auto_resolution(ctx: EmergencyTimingContext) -> None:
    """Emergency should be returned in auto-resolve candidates."""
    assert ctx.emergency is not None
    assert any(e.emergency_id == ctx.emergency.emergency_id for e in ctx.auto_resolve)
    assert not any(e.emergency_id == ctx.emergency.emergency_id for e in ctx.auto_dismiss)


@then("the emergency should be eligible for auto-dismissal")
def then_eligible_for_auto_dismissal(ctx: EmergencyTimingContext) -> None:
    """Emergency should be returned in auto-dismiss candidates."""
    assert ctx.emergency is not None
    assert any(e.emergency_id == ctx.emergency.emergency_id for e in ctx.auto_dismiss)
