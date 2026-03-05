"""
BDD step definitions for new failure type injection.

Tests that FailureInjector correctly modifies telemetry when OIL_PRESSURE_DROP,
VIBRATION_ANOMALY, and BRAKE_DEGRADATION scenarios are active.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.models.enums import FailureScenario, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import VEHICLE_BASELINES
from src.vehicle_agent.failure_injector import FailureInjector

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/failure_injection.feature"


@scenario(FEATURE, "Oil pressure drop is injected into telemetry")
def test_oil_pressure_drop_injected() -> None:
    """Failure: oil pressure decreases after activation."""


@scenario(FEATURE, "Oil pressure does not drop below zero")
def test_oil_pressure_floor() -> None:
    """Failure: oil pressure is clamped at 0."""


@scenario(FEATURE, "Vibration anomaly is injected into telemetry")
def test_vibration_anomaly_injected() -> None:
    """Failure: vibration increases after activation."""


@scenario(FEATURE, "Vibration is capped at 50 m/s²")
def test_vibration_cap() -> None:
    """Failure: vibration is capped at 50 m/s²."""


@scenario(FEATURE, "Brake degradation is injected into telemetry")
def test_brake_degradation_injected() -> None:
    """Failure: brake pad thickness decreases after activation."""


@scenario(FEATURE, "Brake pad thickness does not go below zero")
def test_brake_pad_floor() -> None:
    """Failure: brake pad thickness is clamped at 0."""


@scenario(FEATURE, "Normal telemetry is unchanged when no failure is active")
def test_normal_telemetry_unchanged() -> None:
    """Failure: no modification when no failure is active."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class FailureContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.injector: FailureInjector | None = None
        self.telemetry: VehicleTelemetry | None = None
        self.elapsed_seconds: float = 0.0


@pytest.fixture
def ctx() -> FailureContext:
    """Provide a fresh FailureContext for each scenario."""
    return FailureContext()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_telemetry() -> VehicleTelemetry:
    """Build a baseline ambulance telemetry record."""
    baselines = VEHICLE_BASELINES[VehicleType.AMBULANCE]
    return VehicleTelemetry(
        vehicle_id="TEST-AMB-001",
        timestamp=datetime.now(UTC),
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=0.0,
        odometer_km=baselines["odometer_km"],
        engine_temp_celsius=baselines["engine_temp_celsius"],
        battery_voltage=baselines["battery_voltage"],
        fuel_level_percent=baselines["fuel_level_percent"],
        oil_pressure_bar=baselines["oil_pressure_bar"],
        vibration_ms2=baselines["vibration_ms2"],
        brake_pad_mm=baselines["brake_pad_mm"],
    )


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("a failure injector for an AMBULANCE vehicle")
def failure_injector_ambulance(ctx: FailureContext) -> None:
    """Create a FailureInjector for an ambulance."""
    ctx.injector = FailureInjector(vehicle_type=VehicleType.AMBULANCE)


@given("an OIL_PRESSURE_DROP failure is activated")
def activate_oil_pressure_drop(ctx: FailureContext) -> None:
    """Activate oil pressure drop scenario."""
    assert ctx.injector is not None
    ctx.injector.activate_scenario(FailureScenario.OIL_PRESSURE_DROP)


@given("a VIBRATION_ANOMALY failure is activated")
def activate_vibration_anomaly(ctx: FailureContext) -> None:
    """Activate vibration anomaly scenario."""
    assert ctx.injector is not None
    ctx.injector.activate_scenario(FailureScenario.VIBRATION_ANOMALY)


@given("a BRAKE_DEGRADATION failure is activated")
def activate_brake_degradation(ctx: FailureContext) -> None:
    """Activate brake degradation scenario."""
    assert ctx.injector is not None
    ctx.injector.activate_scenario(FailureScenario.BRAKE_DEGRADATION)


@given("no failure is activated")
def no_failure_activated(ctx: FailureContext) -> None:
    """Ensure no failures are active."""
    assert ctx.injector is not None
    # Already empty by default


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(parsers.parse("the injector is applied to fresh telemetry after {seconds:d} seconds"))
def apply_injector_after_seconds(ctx: FailureContext, seconds: int) -> None:
    """Apply failure injector to fresh telemetry, mocking elapsed time."""
    assert ctx.injector is not None
    ctx.elapsed_seconds = float(seconds)

    with patch.object(
        ctx.injector,
        "get_time_since_activation",
        return_value=float(seconds),
    ):
        ctx.telemetry = ctx.injector.apply_failures(_make_telemetry())


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the telemetry oil_pressure_bar should be less than {threshold:f}"))
def oil_pressure_lt(ctx: FailureContext, threshold: float) -> None:
    """Assert oil_pressure_bar is below the threshold."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.oil_pressure_bar is not None
    assert ctx.telemetry.oil_pressure_bar < threshold, (
        f"oil_pressure_bar {ctx.telemetry.oil_pressure_bar} is not < {threshold}"
    )


@then(
    parsers.parse("the telemetry oil_pressure_bar should be greater than or equal to {threshold:f}")
)
def oil_pressure_gte(ctx: FailureContext, threshold: float) -> None:
    """Assert oil_pressure_bar is >= threshold (floor check)."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.oil_pressure_bar is not None
    assert ctx.telemetry.oil_pressure_bar >= threshold, (
        f"oil_pressure_bar {ctx.telemetry.oil_pressure_bar} is not >= {threshold}"
    )


@then(parsers.parse("the telemetry vibration_ms2 should be greater than {threshold:f}"))
def vibration_gt(ctx: FailureContext, threshold: float) -> None:
    """Assert vibration_ms2 is above the threshold."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.vibration_ms2 is not None
    assert ctx.telemetry.vibration_ms2 > threshold, (
        f"vibration_ms2 {ctx.telemetry.vibration_ms2} is not > {threshold}"
    )


@then(parsers.parse("the telemetry vibration_ms2 should be less than or equal to {threshold:f}"))
def vibration_lte(ctx: FailureContext, threshold: float) -> None:
    """Assert vibration_ms2 is <= threshold (cap check)."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.vibration_ms2 is not None
    assert ctx.telemetry.vibration_ms2 <= threshold, (
        f"vibration_ms2 {ctx.telemetry.vibration_ms2} is not <= {threshold}"
    )


@then(parsers.parse("the telemetry brake_pad_mm should be less than {threshold:f}"))
def brake_pad_lt(ctx: FailureContext, threshold: float) -> None:
    """Assert brake_pad_mm is below the threshold."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.brake_pad_mm is not None
    assert ctx.telemetry.brake_pad_mm < threshold, (
        f"brake_pad_mm {ctx.telemetry.brake_pad_mm} is not < {threshold}"
    )


@then(parsers.parse("the telemetry brake_pad_mm should be greater than or equal to {threshold:f}"))
def brake_pad_gte(ctx: FailureContext, threshold: float) -> None:
    """Assert brake_pad_mm is >= threshold (floor check)."""
    assert ctx.telemetry is not None
    assert ctx.telemetry.brake_pad_mm is not None
    assert ctx.telemetry.brake_pad_mm >= threshold, (
        f"brake_pad_mm {ctx.telemetry.brake_pad_mm} is not >= {threshold}"
    )


@then(
    parsers.parse(
        "the telemetry engine_temp_celsius should be approximately {expected:f} within {tolerance:f} degrees"
    )
)
def engine_temp_approx(ctx: FailureContext, expected: float, tolerance: float) -> None:
    """Assert engine temp is within tolerance of expected (no-failure sanity check)."""
    assert ctx.telemetry is not None
    assert abs(ctx.telemetry.engine_temp_celsius - expected) <= tolerance, (
        f"engine_temp {ctx.telemetry.engine_temp_celsius}°C not within {tolerance}°C of {expected}"
    )
