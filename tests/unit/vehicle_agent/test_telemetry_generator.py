"""Unit tests for telemetry generator."""

import pytest

from src.models.enums import OperationalStatus, VehicleType
from src.vehicle_agent.config import (
    SF_LAT_MAX,
    SF_LAT_MIN,
    SF_LON_MAX,
    SF_LON_MIN,
    AgentConfig,
)
from src.vehicle_agent.navigation import GeometricNavigator, OSMnxNavigator
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator


class TestSimpleTelemetryGenerator:
    """Test suite for SimpleTelemetryGenerator."""

    @pytest.fixture
    def config(self) -> AgentConfig:
        """Create a test configuration."""
        return AgentConfig(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
        )

    @pytest.fixture
    def generator(self, config: AgentConfig) -> SimpleTelemetryGenerator:
        """Create a telemetry generator."""
        return SimpleTelemetryGenerator(config)

    def test_generator_initialization(self, generator: SimpleTelemetryGenerator) -> None:
        """Test generator initializes correctly."""
        assert "engine_temp_celsius" in generator.baselines
        assert "battery_voltage" in generator.baselines

    def test_generate_telemetry(self, generator: SimpleTelemetryGenerator) -> None:
        """Test generating telemetry data."""
        telemetry = generator.generate()

        assert telemetry.vehicle_id == "AMB-001"
        assert telemetry.timestamp is not None

    def test_telemetry_values_in_valid_range(self, generator: SimpleTelemetryGenerator) -> None:
        """Test that generated values are within valid ranges."""
        telemetry = generator.generate()

        # Engine temperature should be around 90°C ± some noise
        assert 80.0 <= telemetry.engine_temp_celsius <= 100.0

        # Battery voltage should be around 13.8V ± some noise
        assert 12.0 <= telemetry.battery_voltage <= 15.0

        # Fuel level should be around 75% ± some noise
        assert 70.0 <= telemetry.fuel_level_percent <= 80.0

    def test_telemetry_location_matches_config(
        self, config: AgentConfig, generator: SimpleTelemetryGenerator
    ) -> None:
        """Test that location matches initial configuration or is updated correctly."""
        telemetry = generator.generate()

        # The location should be close to initial, but it might have moved slightly due to the new movement logic
        assert abs(telemetry.latitude - config.initial_latitude) < 0.1
        assert abs(telemetry.longitude - config.initial_longitude) < 0.1
        # IDLE vehicle should keep a positive patrol speed
        assert telemetry.speed_kmh > 0.0

    def test_add_noise_variability(self, generator: SimpleTelemetryGenerator) -> None:
        """Test that noise produces different values."""
        values = []
        for _ in range(10):
            telemetry = generator.generate()
            values.append(telemetry.engine_temp_celsius)

        # All values should be different (extremely unlikely to be identical with noise)
        assert len(set(values)) > 1

    def test_telemetry_has_all_required_fields(self, generator: SimpleTelemetryGenerator) -> None:
        """Test that telemetry has all required fields."""
        telemetry = generator.generate()

        # Required fields
        assert telemetry.vehicle_id is not None
        assert telemetry.timestamp is not None
        assert telemetry.latitude is not None
        assert telemetry.longitude is not None
        assert telemetry.speed_kmh is not None
        assert telemetry.odometer_km is not None
        assert telemetry.engine_temp_celsius is not None
        assert telemetry.battery_voltage is not None
        assert telemetry.fuel_level_percent is not None

    def test_en_route_toward_out_of_bounds_target_stays_within_sf(self) -> None:
        """EN_ROUTE vehicle moving toward target outside SF stays within boundary."""
        config = AgentConfig(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
            initial_latitude=37.7749,
            initial_longitude=-122.4194,
            initial_status=OperationalStatus.EN_ROUTE,
        )
        gen = SimpleTelemetryGenerator(config)
        # Target south-west of SF (outside or near boundary)
        gen.set_target_location(37.72, -122.52)
        for _ in range(150):
            gen.generate(OperationalStatus.EN_ROUTE)
        assert SF_LAT_MIN <= gen.current_latitude <= SF_LAT_MAX
        assert SF_LON_MIN <= gen.current_longitude <= SF_LON_MAX

    def test_osmnx_provider_falls_back_to_geometric_when_graph_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OSMnx provider should degrade gracefully when graph loading fails."""
        monkeypatch.setattr(OSMnxNavigator, "_load_graph", lambda self: None)
        config = AgentConfig(
            vehicle_id="AMB-001",
            vehicle_type=VehicleType.AMBULANCE,
            navigator_provider="osmnx",
        )
        gen = SimpleTelemetryGenerator(config)
        gen.set_target_location(37.78, -122.41)
        telemetry = gen.generate(OperationalStatus.EN_ROUTE)
        assert telemetry.speed_kmh >= 0.0
        assert SF_LAT_MIN <= telemetry.latitude <= SF_LAT_MAX
        assert SF_LON_MIN <= telemetry.longitude <= SF_LON_MAX

    def test_custom_navigator_injection_is_used(self, config: AgentConfig) -> None:
        """Injected navigator should drive movement deterministically."""
        navigator = GeometricNavigator()
        generator = SimpleTelemetryGenerator(config, navigator=navigator)
        generator.set_target_location(37.7750, -122.4180)
        t1 = generator.generate(OperationalStatus.EN_ROUTE)
        t2 = generator.generate(OperationalStatus.EN_ROUTE)
        assert (t1.latitude != t2.latitude) or (t1.longitude != t2.longitude)
