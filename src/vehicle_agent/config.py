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
