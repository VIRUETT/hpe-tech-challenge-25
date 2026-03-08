"""
Dispatch and vehicle status snapshot models for Project AEGIS.

This module contains data models for unit dispatch records and
real-time vehicle status snapshots maintained by the orchestrator.
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from src.models.enums import OperationalStatus, VehicleType
from src.models.vehicle import Location


class DispatchedUnit(BaseModel):
    """A single unit assigned to an emergency.

    Attributes:
        vehicle_id: Identifier of the dispatched vehicle.
        vehicle_type: Type of vehicle dispatched.
        assigned_at: Timestamp of assignment.
        acknowledged: Whether the vehicle acknowledged the assignment.
        acknowledged_at: Timestamp of acknowledgment.
    """

    vehicle_id: str
    vehicle_type: VehicleType
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    acknowledged: bool = Field(default=False, description="Vehicle acknowledged assignment")
    acknowledged_at: datetime | None = Field(None, description="Timestamp of acknowledgment")


class Dispatch(BaseModel):
    """Record of units dispatched to handle an emergency.

    Created by the DispatchEngine when an emergency is received.
    Tracks which vehicles were assigned and their acknowledgment status.

    Attributes:
        dispatch_id: Unique identifier (auto-generated UUID).
        emergency_id: ID of the emergency this dispatch responds to.
        units: List of dispatched units with their assignment details.
        dispatched_at: Timestamp when dispatch was issued.
        completed_at: Timestamp when all units completed their mission.
        selection_criteria: Description of how units were selected.
        notes: Additional dispatch notes.
    """

    dispatch_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique dispatch record identifier",
    )
    emergency_id: str = Field(..., description="ID of the emergency being responded to")
    units: list[DispatchedUnit] = Field(
        default_factory=list,
        description="List of units dispatched",
    )
    dispatched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when dispatch was issued",
    )
    completed_at: datetime | None = Field(
        None, description="Timestamp when dispatch was completed/resolved"
    )
    selection_criteria: str = Field(
        default="nearest_available",
        description="Criteria used to select units (e.g. nearest_available)",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional notes about this dispatch",
    )

    @property
    def vehicle_ids(self) -> list[str]:
        """List of all vehicle IDs in this dispatch.

        Returns:
            List of vehicle ID strings.
        """
        return [u.vehicle_id for u in self.units]

    @property
    def all_acknowledged(self) -> bool:
        """Whether all dispatched units have acknowledged.

        Returns:
            True if every unit has acknowledged the assignment.
        """
        return all(u.acknowledged for u in self.units)

    model_config = {
        "json_schema_extra": {
            "example": {
                "dispatch_id": "d-550e8400-e29b-41d4-a716-446655440000",
                "emergency_id": "550e8400-e29b-41d4-a716-446655440000",
                "units": [
                    {
                        "vehicle_id": "AMB-001",
                        "vehicle_type": "ambulance",
                        "assigned_at": "2026-02-10T14:32:05.000Z",
                        "acknowledged": True,
                        "acknowledged_at": "2026-02-10T14:32:06.000Z",
                    }
                ],
                "dispatched_at": "2026-02-10T14:32:05.000Z",
                "selection_criteria": "nearest_available",
            }
        }
    }


class VehicleStatusSnapshot(BaseModel):
    """Real-time status snapshot of a vehicle, maintained in-memory by the orchestrator.

    Updated every time a telemetry or heartbeat message is received.
    Used by the DispatchEngine to select available units.

    Attributes:
        vehicle_id: Unique vehicle identifier.
        vehicle_type: Type of vehicle.
        operational_status: Current operational status.
        location: Last known GPS position.
        is_available: Whether the vehicle can be dispatched (derived field).
        current_emergency_id: ID of emergency currently being handled (if any).
        last_seen_at: Timestamp of last received message.
        battery_voltage: Last known battery voltage.
        fuel_level_percent: Last known fuel level.
        has_active_alert: Whether there is an active critical/warning alert.
    """

    vehicle_id: str
    vehicle_type: VehicleType
    operational_status: OperationalStatus = Field(default=OperationalStatus.OFFLINE)
    location: Location | None = Field(None, description="Last known GPS position")
    current_emergency_id: str | None = Field(None, description="Active emergency ID if on mission")
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last received telemetry or heartbeat",
    )
    battery_voltage: float | None = Field(None, description="Last known battery voltage (V)")
    fuel_level_percent: float | None = Field(
        None, ge=0, le=100, description="Last known fuel level (%)"
    )
    engine_temp_celsius: float | None = Field(
        None, description="Last known engine temperature (°C)"
    )
    oil_pressure_bar: float | None = Field(None, description="Last known oil pressure (bar)")
    vibration_ms2: float | None = Field(None, description="Last known vibration level (m/s²)")
    brake_pad_mm: float | None = Field(None, description="Last known brake pad thickness (mm)")
    has_active_alert: bool = Field(
        default=False, description="Whether vehicle has an active warning/critical alert"
    )

    @property
    def is_available(self) -> bool:
        """Whether this vehicle is available for dispatch.

        A vehicle is available if it is IDLE and has no active critical alert.

        Returns:
            True if the vehicle can be dispatched.
        """
        return self.operational_status == OperationalStatus.IDLE and not self.has_active_alert

    model_config = {
        "json_schema_extra": {
            "example": {
                "vehicle_id": "AMB-001",
                "vehicle_type": "ambulance",
                "operational_status": "idle",
                "location": {
                    "latitude": 19.4326,
                    "longitude": -99.1332,
                    "altitude": 2240.0,
                    "accuracy": 5.0,
                    "heading": 0.0,
                    "speed_kmh": 0.0,
                    "timestamp": "2026-02-10T14:32:01.000Z",
                },
                "current_emergency_id": None,
                "last_seen_at": "2026-02-10T14:32:01.000Z",
                "battery_voltage": 13.8,
                "fuel_level_percent": 75.0,
                "has_active_alert": False,
            }
        }
    }
