"""
BDD step definitions for vehicle geographic boundary enforcement.

Tests that IDLE vehicles remain within the San Francisco bounding box defined
in src/vehicle_agent/config.py, and that heading reflection works correctly
when a boundary edge is crossed.
"""

import math

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.models.enums import OperationalStatus, VehicleType
from src.vehicle_agent.config import (
    SF_LAT_MAX,
    SF_LAT_MIN,
    SF_LON_MAX,
    SF_LON_MIN,
    AgentConfig,
)
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/vehicle_boundary.feature"


@scenario(FEATURE, "IDLE vehicle starting inside the boundary stays inside after many ticks")
def test_idle_vehicle_stays_inside_boundary() -> None:
    """Bound: IDLE vehicle never escapes SF box over 500 ticks."""


@scenario(FEATURE, "IDLE vehicle placed beyond the southern boundary is clamped and reflected")
def test_idle_vehicle_southern_boundary() -> None:
    """Bound: southern overshoot is corrected on the first tick."""


@scenario(FEATURE, "IDLE vehicle placed beyond the northern boundary is clamped and reflected")
def test_idle_vehicle_northern_boundary() -> None:
    """Bound: northern overshoot is corrected on the first tick."""


@scenario(FEATURE, "IDLE vehicle placed beyond the western boundary is clamped and reflected")
def test_idle_vehicle_western_boundary() -> None:
    """Bound: western overshoot is corrected on the first tick."""


@scenario(FEATURE, "IDLE vehicle placed beyond the eastern boundary is clamped and reflected")
def test_idle_vehicle_eastern_boundary() -> None:
    """Bound: eastern overshoot is corrected on the first tick."""


@scenario(FEATURE, "EN_ROUTE vehicle dispatched to an emergency within SF is not boundary-clamped")
def test_en_route_vehicle_stays_inside_boundary() -> None:
    """Bound: EN_ROUTE vehicle heading to in-city target stays inside box."""


@scenario(FEATURE, "Stopped vehicle position is unchanged regardless of boundary")
def test_stopped_vehicle_position_unchanged() -> None:
    """Bound: stopped vehicle position is not mutated by the generator."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class VehicleContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize context with empty state."""
        self.generator: SimpleTelemetryGenerator | None = None
        self.status: OperationalStatus = OperationalStatus.IDLE
        self.lat_history: list[float] = []
        self.lon_history: list[float] = []


@pytest.fixture
def ctx() -> VehicleContext:
    """Provide a fresh VehicleContext for each scenario."""
    return VehicleContext()


# ---------------------------------------------------------------------------
# Background step
# ---------------------------------------------------------------------------


@given("the San Francisco bounding box is configured")
def sf_bounding_box_configured() -> None:
    """Verify the module constants are present and form a valid bounding box."""
    assert SF_LAT_MIN < SF_LAT_MAX, "SF_LAT_MIN must be south of SF_LAT_MAX"
    assert SF_LON_MIN < SF_LON_MAX, "SF_LON_MIN must be west of SF_LON_MAX"
    # Sanity-check that the box is centred on San Francisco
    assert 37.0 < SF_LAT_MIN < 38.0
    assert 37.0 < SF_LAT_MAX < 38.0
    assert -123.0 < SF_LON_MIN < -122.0
    assert -123.0 < SF_LON_MAX < -122.0


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


def _make_generator(
    lat: float, lon: float, status: OperationalStatus = OperationalStatus.IDLE
) -> SimpleTelemetryGenerator:
    """Build a SimpleTelemetryGenerator pinned to the given coordinates."""
    config = AgentConfig(
        vehicle_id="TEST-001",
        vehicle_type=VehicleType.AMBULANCE,
        initial_latitude=lat,
        initial_longitude=lon,
        initial_status=status,
        telemetry_frequency_hz=1.0,
    )
    gen = SimpleTelemetryGenerator(config)
    # Override position directly so the initial value is exactly what the
    # scenario specifies (the config validator clamps to global lat/lon ranges
    # but our test values are within those global ranges).
    gen.current_latitude = lat
    gen.current_longitude = lon
    # Set a deterministic heading so boundary-crossing is reproducible.
    gen.heading_degrees = 180.0  # heading South by default
    return gen


@given(parsers.parse("an IDLE vehicle positioned at latitude {lat:f} and longitude {lon:f}"))
def idle_vehicle_at_position(ctx: VehicleContext, lat: float, lon: float) -> None:
    """Create an IDLE vehicle at the given coordinates."""
    ctx.status = OperationalStatus.IDLE
    ctx.generator = _make_generator(lat, lon, OperationalStatus.IDLE)


@given(parsers.parse("an EN_ROUTE vehicle positioned at latitude {lat:f} and longitude {lon:f}"))
def en_route_vehicle_at_position(ctx: VehicleContext, lat: float, lon: float) -> None:
    """Create an EN_ROUTE vehicle at the given coordinates."""
    ctx.status = OperationalStatus.EN_ROUTE
    ctx.generator = _make_generator(lat, lon, OperationalStatus.EN_ROUTE)


@given(
    parsers.parse(
        "a vehicle with status ON_SCENE positioned at latitude {lat:f} and longitude {lon:f}"
    )
)
def on_scene_vehicle_at_position(ctx: VehicleContext, lat: float, lon: float) -> None:
    """Create an ON_SCENE (stopped) vehicle at the given coordinates."""
    ctx.status = OperationalStatus.ON_SCENE
    ctx.generator = _make_generator(lat, lon, OperationalStatus.ON_SCENE)


@given(parsers.parse("the vehicle has a dispatch target at latitude {lat:f} and longitude {lon:f}"))
def vehicle_has_dispatch_target(ctx: VehicleContext, lat: float, lon: float) -> None:
    """Set the EN_ROUTE vehicle's target destination."""
    assert ctx.generator is not None
    ctx.generator.set_target_location(lat, lon)


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(parsers.parse("the vehicle generates {ticks:d} telemetry tick"))
@when(parsers.parse("the vehicle generates {ticks:d} telemetry ticks"))
def vehicle_generates_ticks(ctx: VehicleContext, ticks: int) -> None:
    """Run the generator for the requested number of ticks and record positions."""
    assert ctx.generator is not None
    for _ in range(ticks):
        telemetry = ctx.generator.generate(ctx.status)
        ctx.lat_history.append(telemetry.latitude)
        ctx.lon_history.append(telemetry.longitude)


# ---------------------------------------------------------------------------
# Then steps — latitude assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the vehicle latitude should always be between {lat_min:f} and {lat_max:f}"))
def latitude_always_in_range(ctx: VehicleContext, lat_min: float, lat_max: float) -> None:
    """Assert every recorded latitude is within bounds."""
    for lat in ctx.lat_history:
        assert lat_min <= lat <= lat_max, f"Latitude {lat} is outside [{lat_min}, {lat_max}]"


@then(parsers.parse("the vehicle latitude should be greater than or equal to {threshold:f}"))
def latitude_gte(ctx: VehicleContext, threshold: float) -> None:
    """Assert the most recent latitude is >= threshold."""
    assert ctx.generator is not None
    assert ctx.generator.current_latitude >= threshold, (
        f"Latitude {ctx.generator.current_latitude} < {threshold}"
    )


@then(parsers.parse("the vehicle latitude should be less than or equal to {threshold:f}"))
def latitude_lte(ctx: VehicleContext, threshold: float) -> None:
    """Assert the most recent latitude is <= threshold."""
    assert ctx.generator is not None
    assert ctx.generator.current_latitude <= threshold, (
        f"Latitude {ctx.generator.current_latitude} > {threshold}"
    )


@then(parsers.parse("the vehicle latitude should equal {expected:f}"))
def latitude_equals(ctx: VehicleContext, expected: float) -> None:
    """Assert every recorded latitude equals the expected value (stopped vehicle)."""
    for lat in ctx.lat_history:
        assert lat == pytest.approx(expected, abs=1e-6), f"Latitude {lat} != {expected}"


# ---------------------------------------------------------------------------
# Then steps — longitude assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the vehicle longitude should always be between {lon_min:f} and {lon_max:f}"))
def longitude_always_in_range(ctx: VehicleContext, lon_min: float, lon_max: float) -> None:
    """Assert every recorded longitude is within bounds."""
    for lon in ctx.lon_history:
        assert lon_min <= lon <= lon_max, f"Longitude {lon} is outside [{lon_min}, {lon_max}]"


@then(parsers.parse("the vehicle longitude should be greater than or equal to {threshold:f}"))
def longitude_gte(ctx: VehicleContext, threshold: float) -> None:
    """Assert the most recent longitude is >= threshold."""
    assert ctx.generator is not None
    assert ctx.generator.current_longitude >= threshold, (
        f"Longitude {ctx.generator.current_longitude} < {threshold}"
    )


@then(parsers.parse("the vehicle longitude should be less than or equal to {threshold:f}"))
def longitude_lte(ctx: VehicleContext, threshold: float) -> None:
    """Assert the most recent longitude is <= threshold."""
    assert ctx.generator is not None
    assert ctx.generator.current_longitude <= threshold, (
        f"Longitude {ctx.generator.current_longitude} > {threshold}"
    )


@then(parsers.parse("the vehicle longitude should equal {expected:f}"))
def longitude_equals(ctx: VehicleContext, expected: float) -> None:
    """Assert every recorded longitude equals the expected value (stopped vehicle)."""
    for lon in ctx.lon_history:
        assert lon == pytest.approx(expected, abs=1e-6), f"Longitude {lon} != {expected}"


# ---------------------------------------------------------------------------
# Then steps — heading direction assertions
# ---------------------------------------------------------------------------


@then("the vehicle heading should point northward")
def heading_points_north(ctx: VehicleContext) -> None:
    """Assert the reflected heading has a northward component (cos > 0)."""
    assert ctx.generator is not None
    heading_rad = math.radians(ctx.generator.heading_degrees % 360)
    north_component = math.cos(heading_rad)
    assert north_component > 0, f"Expected northward heading, got {ctx.generator.heading_degrees}°"


@then("the vehicle heading should point southward")
def heading_points_south(ctx: VehicleContext) -> None:
    """Assert the reflected heading has a southward component (cos < 0)."""
    assert ctx.generator is not None
    heading_rad = math.radians(ctx.generator.heading_degrees % 360)
    north_component = math.cos(heading_rad)
    assert north_component < 0, f"Expected southward heading, got {ctx.generator.heading_degrees}°"


@then("the vehicle heading should point eastward")
def heading_points_east(ctx: VehicleContext) -> None:
    """Assert the reflected heading has an eastward component (sin > 0)."""
    assert ctx.generator is not None
    heading_rad = math.radians(ctx.generator.heading_degrees % 360)
    east_component = math.sin(heading_rad)
    assert east_component > 0, f"Expected eastward heading, got {ctx.generator.heading_degrees}°"


@then("the vehicle heading should point westward")
def heading_points_west(ctx: VehicleContext) -> None:
    """Assert the reflected heading has a westward component (sin < 0)."""
    assert ctx.generator is not None
    heading_rad = math.radians(ctx.generator.heading_degrees % 360)
    east_component = math.sin(heading_rad)
    assert east_component < 0, f"Expected westward heading, got {ctx.generator.heading_degrees}°"
