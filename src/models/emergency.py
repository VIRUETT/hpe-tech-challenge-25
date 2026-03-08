"""
Emergency event and city incident models for Project AEGIS.

This module contains data models for emergency events reported in the city
and managed by the orchestrator for dispatch coordination.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum, StrEnum

from pydantic import BaseModel, Field

from src.models.enums import VehicleType
from src.models.vehicle import Location


class EmergencyType(StrEnum):
    """Type of emergency incident."""

    MEDICAL = "medical"  # Heart attack, trauma, etc.
    FIRE = "fire"  # Building fire, vehicle fire
    CRIME = "crime"  # Assault, robbery, active threat
    ACCIDENT = "accident"  # Traffic accident, collision
    HAZMAT = "hazmat"  # Hazardous material spill/leak
    RESCUE = "rescue"  # Trapped persons, water rescue
    NATURAL_DISASTER = "natural_disaster"  # Flood, earthquake, storm


class EmergencyStatus(StrEnum):
    """Lifecycle status of an emergency event."""

    PENDING = "pending"  # Received, awaiting dispatch
    DISPATCHING = "dispatching"  # Units being assigned
    DISPATCHED = "dispatched"  # Units en route
    IN_PROGRESS = "in_progress"  # Units on scene
    RESOLVED = "resolved"  # Emergency handled
    CANCELLED = "cancelled"  # False alarm or duplicate
    DISMISSED = "dismissed"  # Timed out and no longer considered active


class EmergencySeverity(int, Enum):
    """Severity level of the emergency (1=low, 5=critical)."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    CRITICAL = 5


class UnitsRequired(BaseModel):
    """Number of each vehicle type required for an emergency."""

    ambulances: int = Field(default=0, ge=0, description="Number of ambulances needed")
    fire_trucks: int = Field(default=0, ge=0, description="Number of fire trucks needed")
    police: int = Field(default=0, ge=0, description="Number of police units needed")

    @property
    def total(self) -> int:
        """Total number of units required."""
        return self.ambulances + self.fire_trucks + self.police

    def units_of_type(self, vehicle_type: VehicleType) -> int:
        """Return number of units required for a given vehicle type.

        Args:
            vehicle_type: The vehicle type to query.

        Returns:
            Number of units needed for that type.
        """
        mapping = {
            VehicleType.AMBULANCE: self.ambulances,
            VehicleType.FIRE_TRUCK: self.fire_trucks,
            VehicleType.POLICE: self.police,
        }
        return mapping.get(vehicle_type, 0)


# Default units required per emergency type at MODERATE severity (baseline).
# The generator and dispatch engine scale these up by severity multiplier.
EMERGENCY_UNITS_DEFAULTS: dict[EmergencyType, UnitsRequired] = {
    EmergencyType.MEDICAL: UnitsRequired(ambulances=1),
    EmergencyType.FIRE: UnitsRequired(ambulances=1, fire_trucks=2),
    EmergencyType.CRIME: UnitsRequired(police=1),
    EmergencyType.ACCIDENT: UnitsRequired(ambulances=2, police=1),
    EmergencyType.HAZMAT: UnitsRequired(ambulances=1, fire_trucks=2, police=1),
    EmergencyType.RESCUE: UnitsRequired(ambulances=1, fire_trucks=1),
    EmergencyType.NATURAL_DISASTER: UnitsRequired(ambulances=2, fire_trucks=2, police=2),
}

# Severity multipliers: how many extra units to add for each severity tier.
# At LOW (1) we use half the baseline; at CRITICAL (5) we triple it.
# Values are applied as ceil(base_count × multiplier).
SEVERITY_UNIT_MULTIPLIERS: dict[int, float] = {
    EmergencySeverity.LOW.value: 0.5,
    EmergencySeverity.MODERATE.value: 1.0,
    EmergencySeverity.HIGH.value: 1.5,
    EmergencySeverity.SEVERE.value: 2.0,
    EmergencySeverity.CRITICAL.value: 3.0,
}


def scale_units_by_severity(
    base: UnitsRequired,
    severity: EmergencySeverity,
) -> UnitsRequired:
    """Return a new UnitsRequired scaled by the emergency severity level.

    Args:
        base: Baseline units for the emergency type.
        severity: Severity of the incident.

    Returns:
        New UnitsRequired with counts scaled up/down by severity.
    """
    import math

    multiplier = SEVERITY_UNIT_MULTIPLIERS.get(severity.value, 1.0)

    def scale(count: int) -> int:
        if count == 0:
            return 0
        return max(1, math.ceil(count * multiplier))

    return UnitsRequired(
        ambulances=scale(base.ambulances),
        fire_trucks=scale(base.fire_trucks),
        police=scale(base.police),
    )


class Emergency(BaseModel):
    """An emergency event requiring dispatch of one or more units.

    Created when an operator registers a new incident via the REST API.
    The orchestrator processes this and coordinates dispatch.

    Attributes:
        emergency_id: Unique identifier (auto-generated UUID).
        emergency_type: Category of emergency (medical, fire, crime, etc.).
        status: Current lifecycle status of the emergency.
        severity: Severity level from 1 (low) to 5 (critical).
        location: GPS coordinates of the incident.
        address: Human-readable address (optional, for display).
        description: Brief description of the incident.
        units_required: How many of each vehicle type are needed.
        reported_by: Identifier of the operator/system that reported it.
        created_at: Timestamp when the emergency was registered.
        dispatched_at: Timestamp when units were dispatched.
        resolved_at: Timestamp when the emergency was resolved.
        dismissed_at: Timestamp when the emergency was auto-dismissed.
        notes: Additional context or updates.
    """

    emergency_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique emergency identifier",
    )
    emergency_type: EmergencyType
    status: EmergencyStatus = Field(
        default=EmergencyStatus.PENDING,
        description="Current lifecycle status",
    )
    severity: EmergencySeverity = Field(
        default=EmergencySeverity.HIGH,
        description="Severity level 1-5",
    )
    location: Location
    address: str | None = Field(default=None, description="Human-readable address of the incident")
    description: str = Field(..., description="Brief description of the incident")

    units_required: UnitsRequired = Field(
        default_factory=UnitsRequired,
        description="Number of each vehicle type required",
    )

    reported_by: str = Field(
        default="operator",
        description="Identifier of operator or system that reported",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when emergency was registered",
    )
    dispatched_at: datetime | None = Field(
        default=None, description="Timestamp when units were dispatched"
    )
    resolved_at: datetime | None = Field(
        default=None, description="Timestamp when emergency was resolved"
    )
    dismissed_at: datetime | None = Field(
        default=None,
        description="Timestamp when emergency was auto-dismissed",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional notes and status updates",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "emergency_id": "550e8400-e29b-41d4-a716-446655440000",
                "emergency_type": "medical",
                "status": "pending",
                "severity": 4,
                "location": {
                    "latitude": 19.4326,
                    "longitude": -99.1332,
                    "altitude": 2240.0,
                    "accuracy": 10.0,
                    "heading": 0.0,
                    "speed_kmh": 0.0,
                    "timestamp": "2026-02-10T14:32:01.000Z",
                },
                "address": "Av. Insurgentes Sur 1602, Ciudad de Mexico",
                "description": "Cardiac arrest, unconscious adult male",
                "units_required": {"ambulances": 1, "fire_trucks": 0, "police": 0},
                "reported_by": "operator_01",
                "created_at": "2026-02-10T14:32:00.000Z",
            }
        }
    }
