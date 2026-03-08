"""Event payload models exchanged over the AEGIS message bus."""

from __future__ import annotations

from pydantic import BaseModel

from src.models.vehicle import VehicleRegistration


class VehicleRegistrationEvent(BaseModel):
    """Wrapper event for agent registration lifecycle messages."""

    event: str = "vehicle.registered"
    payload: VehicleRegistration
