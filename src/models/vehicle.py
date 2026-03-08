"""
Vehicle identity and state models for Project AEGIS.

This module contains data models for vehicle information and operational state.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import OperationalStatus, VehicleType


class Location(BaseModel):
    """Geographic location."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in degrees")
    altitude: float = Field(default=0.0, description="Altitude in meters above sea level")
    accuracy: float = Field(default=10.0, description="GPS accuracy in meters")
    heading: float = Field(default=0.0, ge=0, le=360, description="Direction in degrees")
    speed_kmh: float = Field(default=0.0, ge=0, description="Speed in km/h")
    timestamp: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "altitude": 15.5,
                "accuracy": 5.0,
                "heading": 45.0,
                "speed_kmh": 65.5,
                "timestamp": "2026-02-10T14:32:01.000Z",
            }
        }
    }


class Vehicle(BaseModel):
    """Vehicle core model."""

    vehicle_id: str = Field(..., description="Unique ID like AMB-001 or FIRE-042")
    vehicle_type: VehicleType = Field(..., description="Type of vehicle")
    operational_status: OperationalStatus = Field(
        default=OperationalStatus.IDLE, description="Current status"
    )
    location: Location | None = Field(None, description="Current location")

    model_config = {
        "json_schema_extra": {
            "example": {
                "vehicle_id": "AMB-001",
                "vehicle_type": "ambulance",
                "operational_status": "en_route",
                "location": {
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                },
            }
        }
    }


class VehicleRegistration(BaseModel):
    """Vehicle registration event emitted when an agent starts."""

    vehicle_id: str
    vehicle_type: VehicleType
    fleet_id: str
    operational_status: OperationalStatus = Field(default=OperationalStatus.IDLE)
    timestamp: datetime
