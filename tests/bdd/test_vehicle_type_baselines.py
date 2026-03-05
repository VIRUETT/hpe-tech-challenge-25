"""
BDD step definitions for per-vehicle-type sensor baselines.

Tests that each vehicle type (AMBULANCE, FIRE_TRUCK, POLICE) generates telemetry
with type-specific baseline sensor readings.
"""

import random
import statistics

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.models.enums import OperationalStatus, VehicleType
from src.vehicle_agent.config import AgentConfig
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/vehicle_type_baselines.feature"


@scenario(FEATURE, "Ambulance engine temperature is near the ambulance baseline")
def test_ambulance_engine_temp() -> None:
    """Baseline: ambulance engine temp stays near 88°C."""


@scenario(FEATURE, "Fire truck engine temperature is near the fire truck baseline")
def test_fire_truck_engine_temp() -> None:
    """Baseline: fire truck engine temp stays near 95°C."""


@scenario(FEATURE, "Police engine temperature is near the police baseline")
def test_police_engine_temp() -> None:
    """Baseline: police engine temp stays near 85°C."""


@scenario(FEATURE, "Ambulance and fire truck baseline temperatures are distinct")
def test_ambulance_fire_truck_temps_distinct() -> None:
    """Baseline: ambulance and fire truck temperatures differ measurably."""


@scenario(FEATURE, "Ambulance battery voltage is near the ambulance baseline")
def test_ambulance_battery_voltage() -> None:
    """Baseline: ambulance battery voltage stays near 13.8 V."""


@scenario(FEATURE, "Fire truck battery voltage is near the fire truck baseline")
def test_fire_truck_battery_voltage() -> None:
    """Baseline: fire truck battery voltage stays near 13.6 V."""


@scenario(FEATURE, "Police battery voltage is near the police baseline")
def test_police_battery_voltage() -> None:
    """Baseline: police battery voltage stays near 14.2 V."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class BaselineContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.generator: SimpleTelemetryGenerator | None = None
        self.generator2: SimpleTelemetryGenerator | None = None
        self.readings: list[float] = []
        self.readings2: list[float] = []


@pytest.fixture
def ctx() -> BaselineContext:
    """Provide a fresh BaselineContext for each scenario."""
    return BaselineContext()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VEHICLE_TYPE_MAP: dict[str, VehicleType] = {
    "AMBULANCE": VehicleType.AMBULANCE,
    "FIRE_TRUCK": VehicleType.FIRE_TRUCK,
    "POLICE": VehicleType.POLICE,
}


def _make_generator(vehicle_type: VehicleType, seed: int = 0) -> SimpleTelemetryGenerator:
    """Build a SimpleTelemetryGenerator for the given vehicle type with a fixed seed."""
    random.seed(seed)
    config = AgentConfig(
        vehicle_id=f"TEST-{vehicle_type.value.upper()}-001",
        vehicle_type=vehicle_type,
        telemetry_frequency_hz=1.0,
    )
    return SimpleTelemetryGenerator(config)


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given(parsers.parse("a telemetry generator for an AMBULANCE vehicle"))
@given(parsers.parse("a telemetry generator for an AMBULANCE vehicle"))
def ambulance_generator(ctx: BaselineContext) -> None:
    """Create a telemetry generator for an ambulance."""
    ctx.generator = _make_generator(VehicleType.AMBULANCE, seed=1)


@given(parsers.parse("a telemetry generator for a FIRE_TRUCK vehicle"))
def fire_truck_generator(ctx: BaselineContext) -> None:
    """Create a telemetry generator for a fire truck."""
    ctx.generator = _make_generator(VehicleType.FIRE_TRUCK, seed=2)


@given(parsers.parse("a telemetry generator for a POLICE vehicle"))
def police_generator(ctx: BaselineContext) -> None:
    """Create a telemetry generator for a police vehicle."""
    ctx.generator = _make_generator(VehicleType.POLICE, seed=3)


@given(parsers.parse("a second telemetry generator for a FIRE_TRUCK vehicle"))
def second_fire_truck_generator(ctx: BaselineContext) -> None:
    """Create a second telemetry generator for a fire truck."""
    ctx.generator2 = _make_generator(VehicleType.FIRE_TRUCK, seed=4)


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(parsers.parse("{ticks:d} telemetry ticks are generated"))
def generate_ticks(ctx: BaselineContext, ticks: int) -> None:
    """Run the primary generator for the given number of ticks and record readings."""
    assert ctx.generator is not None
    for _ in range(ticks):
        t = ctx.generator.generate(OperationalStatus.EN_ROUTE)
        ctx.readings.append(t.engine_temp_celsius)


@when(parsers.parse("{ticks:d} telemetry ticks are generated for each"))
def generate_ticks_for_each(ctx: BaselineContext, ticks: int) -> None:
    """Run both generators and collect engine temperatures."""
    assert ctx.generator is not None
    assert ctx.generator2 is not None
    ctx.readings.clear()
    ctx.readings2.clear()
    for _ in range(ticks):
        t1 = ctx.generator.generate(OperationalStatus.EN_ROUTE)
        ctx.readings.append(t1.engine_temp_celsius)
        t2 = ctx.generator2.generate(OperationalStatus.EN_ROUTE)
        ctx.readings2.append(t2.engine_temp_celsius)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        "the mean engine_temp_celsius should be approximately {expected:f} within {tolerance:f} degrees"
    )
)
def mean_engine_temp_approx(ctx: BaselineContext, expected: float, tolerance: float) -> None:
    """Assert the mean engine temperature is within tolerance of the expected baseline."""
    mean = statistics.mean(ctx.readings)
    assert abs(mean - expected) <= tolerance, (
        f"Mean engine temp {mean:.2f}°C is not within {tolerance}°C of {expected}°C"
    )


@then(parsers.parse("the mean engine temperatures should differ by at least {min_diff:f} degrees"))
def engine_temps_differ(ctx: BaselineContext, min_diff: float) -> None:
    """Assert the two generators produce measurably different mean temperatures."""
    mean1 = statistics.mean(ctx.readings)
    mean2 = statistics.mean(ctx.readings2)
    diff = abs(mean1 - mean2)
    assert diff >= min_diff, f"Engine temperature difference {diff:.2f}°C is less than {min_diff}°C"


@then(
    parsers.parse(
        "the mean battery_voltage should be approximately {expected:f} within {tolerance:f} volts"
    )
)
def mean_battery_voltage_approx(ctx: BaselineContext, expected: float, tolerance: float) -> None:
    """Assert the mean battery voltage is within tolerance of the expected baseline."""
    # Regenerate with battery voltage readings
    assert ctx.generator is not None
    # Reset to capture battery readings — regenerate since readings contain engine_temp
    ctx.generator = _make_generator(ctx.generator.config.vehicle_type, seed=10)
    battery_readings = [
        ctx.generator.generate(OperationalStatus.EN_ROUTE).battery_voltage for _ in range(50)
    ]
    mean = statistics.mean(battery_readings)
    assert abs(mean - expected) <= tolerance, (
        f"Mean battery voltage {mean:.3f} V is not within {tolerance} V of {expected} V"
    )
