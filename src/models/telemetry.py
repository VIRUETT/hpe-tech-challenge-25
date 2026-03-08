"""
Telemetry data models for Project AEGIS.

This module contains high-frequency sensor data structures.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import VehicleType


class VehicleTelemetry(BaseModel):
    """High-frequency sensor data."""

    vehicle_id: str
    vehicle_type: VehicleType | None = Field(
        default=None,
        description="Vehicle type emitted by the agent (preferred over ID prefix inference)",
    )
    timestamp: datetime

    # Location & Movement
    latitude: float = Field(..., ge=-90, le=90, description="Latitude in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in degrees")
    speed_kmh: float = Field(default=0.0, ge=0, description="Speed in km/h")
    odometer_km: float = Field(..., ge=0, description="Total distance traveled in km")

    # Key Metrics for Failure Scenarios
    engine_temp_celsius: float = Field(..., ge=-40, le=200, description="Engine temperature")
    battery_voltage: float = Field(..., ge=0, le=30, description="Battery voltage in volts")
    fuel_level_percent: float = Field(..., ge=0, le=100, description="Fuel level percentage")

    # Extended sensor fields for new failure scenarios
    oil_pressure_bar: float | None = Field(
        default=None, ge=0, le=20, description="Oil pressure in bar (None = not equipped)"
    )
    vibration_ms2: float | None = Field(
        default=None, ge=0, le=50, description="Chassis vibration in m/s² RMS (None = not equipped)"
    )
    brake_pad_mm: float | None = Field(
        default=None, ge=0, le=30, description="Brake pad thickness in mm (None = not equipped)"
    )

    # Optional status reported by vehicle so orchestrator can show ON_SCENE on arrival
    operational_status: str | None = Field(
        default=None,
        description="Current operational status (idle, en_route, on_scene, etc.) when provided",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "vehicle_id": "AMB-001",
                "timestamp": "2026-02-10T14:32:01.000Z",
                "latitude": 37.7749,
                "longitude": -122.4194,
                "speed_kmh": 65.5,
                "engine_temp_celsius": 90.0,
                "battery_voltage": 13.8,
                "fuel_level_percent": 75.0,
                "oil_pressure_bar": 3.5,
                "vibration_ms2": 0.8,
                "brake_pad_mm": 12.0,
            }
        }
    }
