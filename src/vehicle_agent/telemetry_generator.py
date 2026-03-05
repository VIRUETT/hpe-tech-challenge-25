"""
Telemetry generation for vehicle agents.

This module generates synthetic vehicle telemetry data for simulation purposes.
Phase 1: Constant baseline values with Gaussian noise, differentiated per vehicle type.
"""

import math
import random
from datetime import UTC, datetime

import structlog

from src.models.enums import OperationalStatus
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import (
    SF_LAT_MAX,
    SF_LAT_MIN,
    SF_LON_MAX,
    SF_LON_MIN,
    VEHICLE_BASELINES,
    VEHICLE_NOISE_LEVELS,
    AgentConfig,
)

logger = structlog.get_logger(__name__)


class SimpleTelemetryGenerator:
    """Simple telemetry generator using per-vehicle-type baseline values with noise.

    Generates realistic-looking telemetry by adding small random variations
    to baseline constant values.  Baselines are differentiated by vehicle type
    (ambulance, fire truck, police) so that the ML model can learn type-specific
    failure patterns.
    """

    def __init__(self, config: AgentConfig) -> None:
        """
        Initialize telemetry generator.

        Args:
            config: Agent configuration containing vehicle identity and initial state
        """
        self.config = config

        # State variables for movement
        self.current_latitude = config.initial_latitude
        self.current_longitude = config.initial_longitude
        self.target_latitude: float | None = None
        self.target_longitude: float | None = None
        self.current_speed_kmh = 0.0
        self.heading_degrees = random.uniform(0, 360)

        # Per-vehicle-type baseline values (deep-copy so mutations stay per-instance)
        self.baselines: dict[str, float] = dict(VEHICLE_BASELINES[config.vehicle_type])

        # Noise levels are shared (same relative noise for all types)
        self.noise_levels: dict[str, float] = dict(VEHICLE_NOISE_LEVELS)

    def set_target_location(self, lat: float, lon: float) -> None:
        """Set a target destination for the vehicle."""
        self.target_latitude = lat
        self.target_longitude = lon

    def clear_target_location(self) -> None:
        """Clear the current target destination."""
        self.target_latitude = None
        self.target_longitude = None

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
            timestamp=datetime.now(UTC),
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
        # Convert frequency to time step (dt in hours)
        # e.g. 1Hz = 1 second = 1/3600 hours
        dt = 1.0 / (self.config.telemetry_frequency_hz * 3600.0)

        # Base speeds based on vehicle type
        speed = 40.0 if status == OperationalStatus.IDLE else 80.0

        # Earth radius in kilometers
        r_earth = 6371.0

        if status == OperationalStatus.IDLE:
            # Random patrol walk
            self.current_speed_kmh = speed

            # Add some slight random rotation to heading
            self.heading_degrees += random.uniform(-10.0, 10.0)
            bearing = math.radians(self.heading_degrees)
        elif (
            status == OperationalStatus.EN_ROUTE
            and self.target_latitude is not None
            and self.target_longitude is not None
        ):
            # Move towards target
            lat1 = math.radians(self.current_latitude)
            lon1 = math.radians(self.current_longitude)
            lat2 = math.radians(self.target_latitude)
            lon2 = math.radians(self.target_longitude)

            # Haversine distance
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = r_earth * c

            # If we're very close to the target, stop moving
            if distance < 0.05:
                self.current_speed_kmh = 0.0
                return

            self.current_speed_kmh = speed

            # Calculate bearing
            y = math.sin(dlon) * math.cos(lat2)
            x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
            bearing = math.atan2(y, x)
        else:
            # Stopped (ON_SCENE, OFFLINE, OUT_OF_SERVICE, etc)
            self.current_speed_kmh = 0.0
            return

        # Move distance in this tick
        distance_to_move = self.current_speed_kmh * dt

        # New position using haversine formula inverted
        lat1 = math.radians(self.current_latitude)
        lon1 = math.radians(self.current_longitude)

        new_lat = math.asin(
            math.sin(lat1) * math.cos(distance_to_move / r_earth)
            + math.cos(lat1) * math.sin(distance_to_move / r_earth) * math.cos(bearing)
        )

        new_lon = lon1 + math.atan2(
            math.sin(bearing) * math.sin(distance_to_move / r_earth) * math.cos(lat1),
            math.cos(distance_to_move / r_earth) - math.sin(lat1) * math.sin(new_lat),
        )

        self.current_latitude = math.degrees(new_lat)
        self.current_longitude = math.degrees(new_lon)
        self.heading_degrees = math.degrees(bearing)

        # Keep IDLE vehicles within the San Francisco city boundary
        if status == OperationalStatus.IDLE:
            self._apply_sf_boundary()

        # Update odometer
        self.baselines["odometer_km"] += distance_to_move

    def _apply_sf_boundary(self) -> None:
        """Reflect heading and clamp position when an IDLE vehicle crosses the SF boundary.

        When the vehicle exits the bounding box along the latitude axis, the
        north/south component of the heading is inverted (horizontal mirror).
        When it exits along the longitude axis, the east/west component is
        inverted (vertical mirror).  The position is then clamped to the
        nearest boundary edge so the next tick starts inside the box.
        """
        heading_rad = math.radians(self.heading_degrees)
        # Decompose heading into cardinal components
        # heading 0° = North, 90° = East (standard bearing convention)
        north_component = math.cos(heading_rad)
        east_component = math.sin(heading_rad)

        crossed = False

        if self.current_latitude < SF_LAT_MIN:
            self.current_latitude = SF_LAT_MIN
            north_component = abs(north_component)  # force heading northward
            crossed = True
        elif self.current_latitude > SF_LAT_MAX:
            self.current_latitude = SF_LAT_MAX
            north_component = -abs(north_component)  # force heading southward
            crossed = True

        if self.current_longitude < SF_LON_MIN:
            self.current_longitude = SF_LON_MIN
            east_component = abs(east_component)  # force heading eastward
            crossed = True
        elif self.current_longitude > SF_LON_MAX:
            self.current_longitude = SF_LON_MAX
            east_component = -abs(east_component)  # force heading westward
            crossed = True

        if crossed:
            self.heading_degrees = math.degrees(math.atan2(east_component, north_component)) % 360
            logger.debug(
                "boundary_reflection",
                vehicle_id=self.config.vehicle_id,
                new_heading=self.heading_degrees,
                lat=self.current_latitude,
                lon=self.current_longitude,
            )

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
