"""
Failure injection system for vehicle simulation.

Modifies telemetry based on active failure scenarios to simulate realistic degradation.
The injector reads the vehicle-type-specific baselines from config so that failure
offsets are applied correctly regardless of vehicle type.
"""

from datetime import UTC, datetime

from src.models.enums import FailureScenario, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import VEHICLE_BASELINES


class FailureInjector:
    """Injects failure scenarios into vehicle telemetry."""

    def __init__(self, vehicle_type: VehicleType = VehicleType.AMBULANCE) -> None:
        """Initialize the failure injector.

        Args:
            vehicle_type: Type of vehicle whose baselines will be used when
                computing failure offsets. Defaults to AMBULANCE for backward
                compatibility with training scripts.
        """
        self.active_scenarios: dict[FailureScenario, datetime] = {}
        self._baselines = VEHICLE_BASELINES[vehicle_type]

    def activate_scenario(self, scenario: FailureScenario) -> None:
        """
        Activate a failure scenario.

        Args:
            scenario: The failure scenario to activate
        """
        self.active_scenarios[scenario] = datetime.now(UTC)

    def deactivate_scenario(self, scenario: FailureScenario) -> None:
        """
        Deactivate a failure scenario.

        Args:
            scenario: The failure scenario to deactivate
        """
        self.active_scenarios.pop(scenario, None)

    def get_time_since_activation(self, scenario: FailureScenario) -> float:
        """
        Get seconds since a scenario was activated.

        Args:
            scenario: The failure scenario to check

        Returns:
            Seconds since activation, or 0.0 if not active
        """
        if scenario not in self.active_scenarios:
            return 0.0
        elapsed = datetime.now(UTC) - self.active_scenarios[scenario]
        return elapsed.total_seconds()

    def apply_failures(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """
        Apply all active failure scenarios to telemetry.

        Args:
            telemetry: Original telemetry data

        Returns:
            Modified telemetry with failures applied
        """
        modified = telemetry.model_copy(deep=True)

        for scenario in self.active_scenarios:
            if scenario == FailureScenario.ENGINE_OVERHEAT:
                modified = self._apply_engine_overheat(modified)
            elif scenario == FailureScenario.BATTERY_DEGRADATION:
                modified = self._apply_battery_degradation(modified)
            elif scenario == FailureScenario.FUEL_LEAK:
                modified = self._apply_fuel_leak(modified)
            elif scenario == FailureScenario.OIL_PRESSURE_DROP:
                modified = self._apply_oil_pressure_drop(modified)
            elif scenario == FailureScenario.VIBRATION_ANOMALY:
                modified = self._apply_vibration_anomaly(modified)
            elif scenario == FailureScenario.BRAKE_DEGRADATION:
                modified = self._apply_brake_degradation(modified)

        return modified

    def _apply_engine_overheat(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply engine overheat scenario.

        Temperature rises +2°C per minute from the vehicle-type baseline,
        capped at 150°C.
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.ENGINE_OVERHEAT)
        elapsed_minutes = elapsed_seconds / 60.0

        base_temp = self._baselines["engine_temp_celsius"]
        temp_increase = elapsed_minutes * 2.0
        telemetry.engine_temp_celsius = min(base_temp + temp_increase, 150.0)

        return telemetry

    def _apply_battery_degradation(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply battery degradation scenario.

        Voltage drops -0.1 V every 5 minutes from the vehicle-type baseline.
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.BATTERY_DEGRADATION)
        elapsed_minutes = elapsed_seconds / 60.0

        base_voltage = self._baselines["battery_voltage"]
        voltage_drop = (elapsed_minutes / 5.0) * 0.1
        telemetry.battery_voltage = max(0.0, base_voltage - voltage_drop)

        return telemetry

    def _apply_fuel_leak(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply fuel leak scenario.

        Fuel drains 5 % per minute from the vehicle-type baseline.
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.FUEL_LEAK)
        elapsed_minutes = elapsed_seconds / 60.0

        base_fuel = self._baselines["fuel_level_percent"]
        leak_amount = elapsed_minutes * 5.0
        telemetry.fuel_level_percent = max(0.0, base_fuel - leak_amount)

        return telemetry

    def _apply_oil_pressure_drop(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply oil pressure drop scenario.

        Pressure drops -0.3 bar per minute from the vehicle-type baseline.
        Critical threshold is <1.0 bar.
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.OIL_PRESSURE_DROP)
        elapsed_minutes = elapsed_seconds / 60.0

        base_pressure = self._baselines["oil_pressure_bar"]
        pressure_drop = elapsed_minutes * 0.3
        telemetry.oil_pressure_bar = max(0.0, base_pressure - pressure_drop)

        return telemetry

    def _apply_vibration_anomaly(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply vibration anomaly scenario.

        Vibration rises +0.5 m/s² per minute from the vehicle-type baseline.
        Critical threshold is >8 m/s².
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.VIBRATION_ANOMALY)
        elapsed_minutes = elapsed_seconds / 60.0

        base_vib = self._baselines["vibration_ms2"]
        vib_increase = elapsed_minutes * 0.5
        telemetry.vibration_ms2 = min(base_vib + vib_increase, 50.0)

        return telemetry

    def _apply_brake_degradation(self, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        """Apply brake degradation scenario.

        Brake pad thickness decreases -0.2 mm per minute from baseline.
        Warning threshold <6 mm; critical threshold <3 mm.
        """
        elapsed_seconds = self.get_time_since_activation(FailureScenario.BRAKE_DEGRADATION)
        elapsed_minutes = elapsed_seconds / 60.0

        base_pad = self._baselines["brake_pad_mm"]
        pad_wear = elapsed_minutes * 0.2
        telemetry.brake_pad_mm = max(0.0, base_pad - pad_wear)

        return telemetry
