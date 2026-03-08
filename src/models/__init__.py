"""
Data models for Project AEGIS.

This package contains all Pydantic models for vehicle telemetry, alerts,
emergencies, and dispatch.
"""

# Enums
# Alert models
from .alerts import PredictiveAlert

# Dispatch models
from .dispatch import Dispatch, DispatchedUnit, VehicleStatusSnapshot

# Emergency models
from .emergency import (
    EMERGENCY_UNITS_DEFAULTS,
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    UnitsRequired,
)
from .enums import (
    AlertSeverity,
    FailureCategory,
    FailureScenario,
    OperationalStatus,
    VehicleType,
)
from .events import VehicleRegistrationEvent

# Telemetry models
from .telemetry import VehicleTelemetry

# Vehicle models
from .vehicle import Location, Vehicle, VehicleRegistration

__all__ = [
    # Enums
    "AlertSeverity",
    "FailureCategory",
    "FailureScenario",
    "OperationalStatus",
    "VehicleType",
    # Emergency
    "EMERGENCY_UNITS_DEFAULTS",
    "Emergency",
    "EmergencySeverity",
    "EmergencyStatus",
    "EmergencyType",
    "UnitsRequired",
    # Dispatch
    "Dispatch",
    "DispatchedUnit",
    "VehicleStatusSnapshot",
    # Vehicle
    "Location",
    "Vehicle",
    "VehicleRegistration",
    "VehicleRegistrationEvent",
    # Telemetry
    "VehicleTelemetry",
    # Alerts
    "PredictiveAlert",
]
