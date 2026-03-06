"""Unit tests for failure injector."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import FailureScenario, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import VEHICLE_BASELINES
from src.vehicle_agent.failure_injector import FailureInjector

# FailureInjector uses vehicle-type baselines from config, not incoming telemetry.
AMBULANCE = VEHICLE_BASELINES[VehicleType.AMBULANCE]


class TestFailureInjector:
    """Test suite for FailureInjector."""

    @pytest.fixture
    def injector(self) -> FailureInjector:
        """Create failure injector."""
        return FailureInjector()

    @pytest.fixture
    def sample_telemetry(self) -> VehicleTelemetry:
        """Create baseline normal telemetry."""
        return VehicleTelemetry(
            vehicle_id="AMB-001",
            timestamp=datetime.now(UTC),
            latitude=37.7749,
            longitude=-122.4194,
            speed_kmh=65.0,
            odometer_km=15000.5,
            engine_temp_celsius=90.0,
            battery_voltage=13.8,
            fuel_level_percent=75.0,
        )

    def test_injector_initialization(self, injector: FailureInjector) -> None:
        """Test initial state."""
        assert len(injector.active_scenarios) == 0

    def test_activate_scenario(self, injector: FailureInjector) -> None:
        """Test activating a scenario."""
        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)
        assert FailureScenario.ENGINE_OVERHEAT in injector.active_scenarios
        assert len(injector.active_scenarios) == 1

    def test_deactivate_scenario(self, injector: FailureInjector) -> None:
        """Test deactivating a scenario."""
        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)
        injector.deactivate_scenario(FailureScenario.ENGINE_OVERHEAT)
        assert FailureScenario.ENGINE_OVERHEAT not in injector.active_scenarios

    def test_get_time_since_activation_not_active(self, injector: FailureInjector) -> None:
        """Test time since activation for inactive scenario."""
        assert injector.get_time_since_activation(FailureScenario.ENGINE_OVERHEAT) == 0.0

    @patch("src.vehicle_agent.failure_injector.datetime")
    def test_get_time_since_activation_active(
        self, mock_datetime: MagicMock, injector: FailureInjector
    ) -> None:
        """Test time since activation calculation."""
        # Set up mock times
        start_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        current_time = start_time + timedelta(seconds=30)

        # Configure mock to return specific times
        mock_datetime.now.side_effect = [start_time, current_time]

        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)
        elapsed = injector.get_time_since_activation(FailureScenario.ENGINE_OVERHEAT)

        assert elapsed == 30.0

    def test_apply_failures_no_active_scenarios(
        self, injector: FailureInjector, sample_telemetry: VehicleTelemetry
    ) -> None:
        """Test applying failures when none are active."""
        modified = injector.apply_failures(sample_telemetry)

        # Values should be unchanged
        assert modified.engine_temp_celsius == sample_telemetry.engine_temp_celsius
        assert modified.battery_voltage == sample_telemetry.battery_voltage
        assert modified.fuel_level_percent == sample_telemetry.fuel_level_percent

    @patch("src.vehicle_agent.failure_injector.FailureInjector.get_time_since_activation")
    def test_apply_engine_overheat(
        self,
        mock_get_time: MagicMock,
        injector: FailureInjector,
        sample_telemetry: VehicleTelemetry,
    ) -> None:
        """Test engine overheat scenario progression from ambulance baseline."""
        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)
        base = AMBULANCE["engine_temp_celsius"]

        # Initial state (0 minutes): baseline + 0
        mock_get_time.return_value = 0.0
        mod_0 = injector.apply_failures(sample_telemetry)
        assert mod_0.engine_temp_celsius == base

        # After 5 minutes: baseline + 2°C/min * 5 = +10
        mock_get_time.return_value = 300.0
        mod_5 = injector.apply_failures(sample_telemetry)
        assert mod_5.engine_temp_celsius == base + 10.0

        # After 15 minutes: baseline + 2°C/min * 15 = +30
        mock_get_time.return_value = 900.0
        mod_15 = injector.apply_failures(sample_telemetry)
        assert mod_15.engine_temp_celsius == base + 30.0

    @patch("src.vehicle_agent.failure_injector.FailureInjector.get_time_since_activation")
    def test_apply_battery_degradation(
        self,
        mock_get_time: MagicMock,
        injector: FailureInjector,
        sample_telemetry: VehicleTelemetry,
    ) -> None:
        """Test battery degradation progression."""
        injector.activate_scenario(FailureScenario.BATTERY_DEGRADATION)

        # Initial state (0 minutes)
        mock_get_time.return_value = 0.0
        mod_0 = injector.apply_failures(sample_telemetry)
        assert mod_0.battery_voltage == 13.8

        # After 25 minutes (25 * 60 seconds)
        # Should decrease by 0.1V per 5 minutes = 0.5V drop
        mock_get_time.return_value = 1500.0
        mod_25 = injector.apply_failures(sample_telemetry)
        assert mod_25.battery_voltage == pytest.approx(13.3)

    @patch("src.vehicle_agent.failure_injector.FailureInjector.get_time_since_activation")
    def test_apply_fuel_leak(
        self,
        mock_get_time: MagicMock,
        injector: FailureInjector,
        sample_telemetry: VehicleTelemetry,
    ) -> None:
        """Test fuel leak progression from ambulance baseline."""
        injector.activate_scenario(FailureScenario.FUEL_LEAK)
        base = AMBULANCE["fuel_level_percent"]

        # Initial state (0 minutes): baseline - 0
        mock_get_time.return_value = 0.0
        mod_0 = injector.apply_failures(sample_telemetry)
        assert mod_0.fuel_level_percent == base

        # After 5 minutes: baseline - 5%/min * 5 = -25%
        mock_get_time.return_value = 300.0
        mod_5 = injector.apply_failures(sample_telemetry)
        assert mod_5.fuel_level_percent == base - 25.0

    @patch("src.vehicle_agent.failure_injector.FailureInjector.get_time_since_activation")
    def test_apply_multiple_failures(
        self,
        mock_get_time: MagicMock,
        injector: FailureInjector,
        sample_telemetry: VehicleTelemetry,
    ) -> None:
        """Test applying multiple scenarios simultaneously from ambulance baselines."""
        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)
        injector.activate_scenario(FailureScenario.BATTERY_DEGRADATION)

        # Simulate 10 minutes elapsed
        mock_get_time.return_value = 600.0

        modified = injector.apply_failures(sample_telemetry)

        # Engine: baseline + 2°C/min * 10; battery: baseline - 0.1V per 5 min * 2
        assert modified.engine_temp_celsius == AMBULANCE["engine_temp_celsius"] + 20.0
        assert modified.battery_voltage == pytest.approx(
            AMBULANCE["battery_voltage"] - 0.2
        )

    def test_telemetry_immutability(
        self, injector: FailureInjector, sample_telemetry: VehicleTelemetry
    ) -> None:
        """Test that original telemetry is not modified."""
        injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)

        original_temp = sample_telemetry.engine_temp_celsius

        # Apply failure with high elapsed time
        with patch(
            "src.vehicle_agent.failure_injector.FailureInjector.get_time_since_activation",
            return_value=3600.0,
        ):
            modified = injector.apply_failures(sample_telemetry)

        # Original should be untouched
        assert sample_telemetry.engine_temp_celsius == original_temp
        assert modified.engine_temp_celsius > original_temp
