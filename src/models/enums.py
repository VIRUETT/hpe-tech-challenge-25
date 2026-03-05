"""
Enumerations for Project AEGIS.

This module contains all enum definitions used throughout the system.
"""

from enum import StrEnum


class VehicleType(StrEnum):
    """Type of emergency vehicle."""

    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"


class OperationalStatus(StrEnum):
    """Current operational status of a vehicle."""

    IDLE = "idle"  # At station, ready for dispatch
    EN_ROUTE = "en_route"  # Responding to emergency
    ON_SCENE = "on_scene"  # At emergency location
    RETURNING = "returning"  # Returning to station
    MAINTENANCE = "maintenance"  # Scheduled maintenance
    OUT_OF_SERVICE = "out_of_service"  # Broken/unavailable
    OFFLINE = "offline"  # Not connected to system


class AlertSeverity(StrEnum):
    """Severity level of predictive alerts."""

    CRITICAL = "critical"  # Immediate action required
    WARNING = "warning"  # Action needed soon
    INFO = "info"  # Informational only


class FailureCategory(StrEnum):
    """Category of vehicle component failure."""

    ENGINE = "engine"
    ELECTRICAL = "electrical"
    FUEL = "fuel"
    OTHER = "other"


class FailureScenario(StrEnum):
    """Predefined failure modes for simulation."""

    ENGINE_OVERHEAT = "engine_overheat"
    BATTERY_DEGRADATION = "battery_degradation"
    FUEL_LEAK = "fuel_leak"
    OIL_PRESSURE_DROP = "oil_pressure_drop"
    VIBRATION_ANOMALY = "vibration_anomaly"
    BRAKE_DEGRADATION = "brake_degradation"
