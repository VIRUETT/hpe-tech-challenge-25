"""
Configuration management for vehicle agents.

This module provides typed configuration for vehicle agents using Pydantic.
"""

from pydantic import Field
from pydantic_settings import BaseSettings

from src.models.enums import OperationalStatus, VehicleType

# San Francisco geographic bounding box.
# Vehicles operating in IDLE mode are constrained to this region and will
# reflect their heading when they reach any boundary edge.
SF_LAT_MIN: float = 37.708  # Southern boundary (near Daly City border)
SF_LAT_MAX: float = 37.833  # Northern boundary (near Golden Gate)
SF_LON_MIN: float = -122.527  # Western boundary (Ocean Beach)
SF_LON_MAX: float = -122.349  # Eastern boundary (near Bay Bridge toll)


# ---------------------------------------------------------------------------
# Per-vehicle-type sensor baselines
# ---------------------------------------------------------------------------
# Engine temperature baselines reflect real-world operating differences:
#   - Ambulances run lighter diesel engines, typically 85–90°C
#   - Fire trucks run heavy-duty V8/V10 diesels under constant load, ~92–98°C
#   - Police units (interceptor SUVs/sedans) run at ~82–87°C
#
# Oil pressure baselines (bar):  normal idle/operating band per type
# Vibration baselines (m/s²):    typical chassis vibration while moving
# Brake pad baselines (mm):      new pad ~14 mm; warning <6 mm; critical <3 mm
# ---------------------------------------------------------------------------

VEHICLE_BASELINES: dict[VehicleType, dict[str, float]] = {
    VehicleType.AMBULANCE: {
        "engine_temp_celsius": 88.0,
        "battery_voltage": 13.8,
        "fuel_level_percent": 78.0,
        "odometer_km": 42000.0,
        "oil_pressure_bar": 3.5,
        "vibration_ms2": 0.8,
        "brake_pad_mm": 12.0,
    },
    VehicleType.FIRE_TRUCK: {
        "engine_temp_celsius": 95.0,
        "battery_voltage": 13.6,
        "fuel_level_percent": 85.0,
        "odometer_km": 55000.0,
        "oil_pressure_bar": 4.2,
        "vibration_ms2": 1.2,
        "brake_pad_mm": 10.0,
    },
    VehicleType.POLICE: {
        "engine_temp_celsius": 85.0,
        "battery_voltage": 14.2,
        "fuel_level_percent": 70.0,
        "odometer_km": 68000.0,
        "oil_pressure_bar": 3.2,
        "vibration_ms2": 0.6,
        "brake_pad_mm": 8.0,
    },
}

# Noise levels as fractions of the baseline value (used as ±2σ of Gaussian noise).
VEHICLE_NOISE_LEVELS: dict[str, float] = {
    "engine_temp_celsius": 0.02,  # ±2%
    "battery_voltage": 0.02,
    "fuel_level_percent": 0.01,
    "odometer_km": 0.0,  # Monotonically increasing; noise added elsewhere
    "oil_pressure_bar": 0.03,  # ±3%
    "vibration_ms2": 0.05,  # ±5%
    "brake_pad_mm": 0.0,  # Changes only during failure injection
}


class AgentConfig(BaseSettings):
    """Configuration for a single vehicle agent.

    This configuration can be loaded from environment variables or passed directly.
    Environment variables should be prefixed with AEGIS_ (e.g., AEGIS_VEHICLE_ID).
    """

    # Vehicle Identity
    vehicle_id: str = Field(..., description="Unique vehicle identifier (e.g., AMB-001)")
    vehicle_type: VehicleType = Field(..., description="Type of emergency vehicle")
    fleet_id: str = Field(default="fleet01", description="Fleet identifier")

    # Redis Connection
    redis_host: str = Field(default="localhost", description="Redis server hostname")
    redis_port: int = Field(default=6379, ge=1, le=65535, description="Redis server port")
    redis_password: str | None = Field(default=None, description="Redis password (optional)")
    redis_db: int = Field(default=0, ge=0, le=15, description="Redis database number")

    # Telemetry Configuration
    telemetry_frequency_hz: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Telemetry generation frequency in Hz"
    )

    # Navigation / Routing
    navigator_provider: str = Field(
        default="geometric",
        description="Movement provider: geometric | osmnx",
    )
    osmnx_place_name: str = Field(
        default="San Francisco, California, USA",
        description="OSM place used to load the road network graph",
    )
    osmnx_network_type: str = Field(
        default="drive",
        description="OSMnx network type (drive, walk, bike, all)",
    )

    # Initial State
    initial_status: OperationalStatus = Field(
        default=OperationalStatus.IDLE, description="Starting operational status"
    )
    initial_latitude: float = Field(
        default=37.7749, ge=-90, le=90, description="Starting latitude (San Francisco)"
    )
    initial_longitude: float = Field(
        default=-122.4194, ge=-180, le=180, description="Starting longitude (San Francisco)"
    )
    initial_altitude: float = Field(default=0.0, description="Starting altitude in meters")

    # Agent Metadata
    agent_version: str = Field(default="1.0.0", description="Vehicle agent software version")

    model_config = {
        "env_prefix": "AEGIS_",
        "case_sensitive": False,
    }

    def get_channel_name(self, channel_type: str) -> str:
        """
        Generate Redis channel name following AEGIS naming convention.

        Args:
            channel_type: Type of channel (telemetry, alerts, status, heartbeat, commands)

        Returns:
            Full Redis channel name

        Example:
            >>> config.get_channel_name("telemetry")
            'aegis:fleet01:telemetry:AMB-001'
        """
        return f"aegis:{self.fleet_id}:{channel_type}:{self.vehicle_id}"
