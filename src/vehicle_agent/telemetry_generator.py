"""
Telemetry generation for vehicle agents.

This module generates synthetic vehicle telemetry data for simulation purposes.
Phase 1: Constant baseline values with Gaussian noise, differentiated per vehicle type.
"""

import random

import structlog

from src.core.time import Clock, RealClock
from src.models.enums import OperationalStatus
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import (
    VEHICLE_BASELINES,
    VEHICLE_NOISE_LEVELS,
    AgentConfig,
)
from src.vehicle_agent.navigation import NavigatorProvider, build_navigator

logger = structlog.get_logger(__name__)


class SimpleTelemetryGenerator:
    """Simple telemetry generator using per-vehicle-type baseline values with noise.

    Generates realistic-looking telemetry by adding small random variations
    to baseline constant values.  Baselines are differentiated by vehicle type
    (ambulance, fire truck, police) so that the ML model can learn type-specific
    failure patterns.
    """

    def __init__(
        self,
        config: AgentConfig,
        clock: Clock | None = None,
        navigator: NavigatorProvider | None = None,
    ) -> None:
        """
        Initialize telemetry generator.

        Args:
            config: Agent configuration containing vehicle identity and initial state
        """
        self.config = config
        self.clock = clock or RealClock()

        # State variables for movement
        self.current_latitude = config.initial_latitude
        self.current_longitude = config.initial_longitude
        self.current_speed_kmh = 0.0
        self.heading_degrees = 0.0

        # Per-vehicle-type baseline values (deep-copy so mutations stay per-instance)
        self.baselines: dict[str, float] = dict(VEHICLE_BASELINES[config.vehicle_type])

        # Noise levels are shared (same relative noise for all types)
        self.noise_levels: dict[str, float] = dict(VEHICLE_NOISE_LEVELS)
        self.navigator = navigator or build_navigator(
            config.navigator_provider,
            osmnx_place_name=config.osmnx_place_name,
            osmnx_network_type=config.osmnx_network_type,
        )

    def set_target_location(self, lat: float, lon: float) -> None:
        """Set a target destination for the vehicle."""
        self.navigator.set_target(
            current_lat=self.current_latitude,
            current_lon=self.current_longitude,
            target_lat=lat,
            target_lon=lon,
        )

    def clear_target_location(self) -> None:
        """Clear the current target destination."""
        self.navigator.clear_target()

    def generate(self, status: OperationalStatus | None = None) -> VehicleTelemetry:
        """
        Generate a single telemetry reading with current timestamp.

        Args:
            status: Optional operational status to dictate movement. If None, uses initial_status.

        Returns:
            VehicleTelemetry object with all required fields
        """
        if status is None:
            status = self.config.initial_status

        self._update_position(status)

        # Generate telemetry with noise
        telemetry = VehicleTelemetry(
            vehicle_id=self.config.vehicle_id,
            vehicle_type=self.config.vehicle_type,
            timestamp=self.clock.now(),
            latitude=self.current_latitude,
            longitude=self.current_longitude,
            speed_kmh=self.current_speed_kmh,
            odometer_km=self._add_noise("odometer_km"),
            engine_temp_celsius=self._add_noise("engine_temp_celsius"),
            battery_voltage=self._add_noise("battery_voltage"),
            fuel_level_percent=self._add_noise("fuel_level_percent"),
            oil_pressure_bar=self._add_noise("oil_pressure_bar"),
            vibration_ms2=self._add_noise("vibration_ms2"),
            brake_pad_mm=self._add_noise("brake_pad_mm"),
        )

        logger.debug(
            "telemetry_generated",
            vehicle_id=self.config.vehicle_id,
        )

        return telemetry

    def _update_position(self, status: OperationalStatus) -> None:
        """Update vehicle position based on state and target."""
        dt = 1.0 / (self.config.telemetry_frequency_hz * 3600.0)
        nav = self.navigator.step(
            current_lat=self.current_latitude,
            current_lon=self.current_longitude,
            heading_degrees=self.heading_degrees,
            status=status,
            dt_hours=dt,
        )
        self.current_latitude = nav.latitude
        self.current_longitude = nav.longitude
        self.heading_degrees = nav.heading_degrees
        self.current_speed_kmh = nav.speed_kmh
        self.baselines["odometer_km"] += nav.distance_moved_km

    def _add_noise(self, metric: str) -> float:
        """
        Add Gaussian noise to a baseline metric value.

        Args:
            metric: Name of the metric in self.baselines

        Returns:
            Baseline value with added noise
        """
        baseline = self.baselines[metric]
        noise_level = self.noise_levels[metric]
        return self._add_noise_raw(baseline, noise_level)

    def _add_noise_raw(self, baseline: float, noise_level: float) -> float:
        """
        Add Gaussian noise to a raw value.

        Args:
            baseline: Base value
            noise_level: Noise as fraction of baseline (e.g., 0.02 = ±2%)

        Returns:
            Value with added Gaussian noise, clamped to reasonable ranges
        """
        if noise_level == 0.0:
            return baseline

        # Calculate standard deviation (noise_level is ~±2σ for 95% confidence)
        std_dev = abs(baseline * noise_level) / 2.0

        # Add Gaussian noise
        noise = random.gauss(0, std_dev)
        result = baseline + noise

        # Clamp to reasonable ranges to avoid validation errors
        # Percentages should never exceed 100 or go below 0
        if baseline <= 100.0 and baseline >= 0.0:
            result = max(0.0, min(100.0, result))

        return result
