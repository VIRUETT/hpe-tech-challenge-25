import structlog

from src.core.time import Clock, RealClock
from src.models.alerts import PredictiveAlert
from src.models.dispatch import VehicleStatusSnapshot
from src.models.enums import OperationalStatus, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.models.vehicle import Location

logger = structlog.get_logger(__name__)


class FleetService:
    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or RealClock()
        self.fleet: dict[str, VehicleStatusSnapshot] = {}
        self.active_alerts: dict[str, PredictiveAlert] = {}

    def process_telemetry(
        self, telemetry: VehicleTelemetry
    ) -> tuple[bool, VehicleType | None, VehicleStatusSnapshot]:
        """
        Update fleet state from telemetry.
        Returns a tuple: (is_new_vehicle, vehicle_type, updated_snapshot)
        """
        vehicle_id = telemetry.vehicle_id
        is_new = False
        vehicle_type = None

        snap = self.fleet.get(vehicle_id)
        if snap is None:
            is_new = True
            vehicle_type = telemetry.vehicle_type
            if vehicle_type is None:
                raise ValueError("Vehicle type is required for new vehicle registration")
            snap = VehicleStatusSnapshot.model_validate(
                {
                    "vehicle_id": vehicle_id,
                    "vehicle_type": vehicle_type,
                    "operational_status": OperationalStatus.IDLE,
                }
            )
            self.fleet[vehicle_id] = snap
        elif telemetry.vehicle_type is not None:
            snap.vehicle_type = telemetry.vehicle_type

        # Update last seen timestamp
        snap.last_seen_at = self._clock.now()

        # Update location
        try:
            snap.location = Location(
                latitude=telemetry.latitude,
                longitude=telemetry.longitude,
                timestamp=telemetry.timestamp,
            )
        except Exception:
            pass  # Location parse failure is non-fatal

        # Update key health metrics
        snap.battery_voltage = float(telemetry.battery_voltage)
        snap.fuel_level_percent = float(telemetry.fuel_level_percent)
        snap.engine_temp_celsius = float(telemetry.engine_temp_celsius)

        snap.oil_pressure_bar = (
            float(telemetry.oil_pressure_bar) if telemetry.oil_pressure_bar is not None else None
        )
        snap.vibration_ms2 = (
            float(telemetry.vibration_ms2) if telemetry.vibration_ms2 is not None else None
        )
        snap.brake_pad_mm = (
            float(telemetry.brake_pad_mm) if telemetry.brake_pad_mm is not None else None
        )

        return is_new, vehicle_type, snap

    def register_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: VehicleType,
        status: OperationalStatus = OperationalStatus.IDLE,
    ) -> tuple[bool, VehicleStatusSnapshot]:
        """Register vehicle metadata before first telemetry arrives."""
        existing = self.fleet.get(vehicle_id)
        if existing is not None:
            existing.vehicle_type = vehicle_type
            existing.operational_status = status
            existing.last_seen_at = self._clock.now()
            return False, existing

        snapshot = VehicleStatusSnapshot.model_validate(
            {
                "vehicle_id": vehicle_id,
                "vehicle_type": vehicle_type,
                "operational_status": status,
            }
        )
        snapshot.last_seen_at = self._clock.now()
        self.fleet[vehicle_id] = snapshot
        return True, snapshot

    def handle_alert(self, alert: PredictiveAlert) -> None:
        """Update vehicle state to reflect an active alert."""
        vehicle_id = alert.vehicle_id
        if vehicle_id in self.fleet:
            self.fleet[vehicle_id].has_active_alert = True
        self.active_alerts[vehicle_id] = alert

    def clear_alert(self, vehicle_id: str) -> None:
        """Clear the alert state and return vehicle to IDLE."""
        if vehicle_id in self.fleet:
            self.fleet[vehicle_id].has_active_alert = False
            self.fleet[vehicle_id].operational_status = OperationalStatus.IDLE
        self.active_alerts.pop(vehicle_id, None)

    def get_summary(self, active_emergencies_count: int) -> dict:
        """Calculate and return the fleet summary metrics."""
        total = len(self.fleet)
        available = sum(1 for s in self.fleet.values() if s.is_available)
        on_mission = sum(
            1
            for s in self.fleet.values()
            if s.operational_status.value in ("en_route", "on_scene", "returning")
        )
        by_type: dict[str, dict[str, int]] = {}

        for snap in self.fleet.values():
            key = snap.vehicle_type.value
            if key not in by_type:
                by_type[key] = {"total": 0, "available": 0}
            by_type[key]["total"] += 1
            if snap.is_available:
                by_type[key]["available"] += 1

        return {
            "total_vehicles": total,
            "available_vehicles": available,
            "on_mission": on_mission,
            "vehicles_with_alerts": len(self.active_alerts),
            "active_emergencies": active_emergencies_count,
            "by_type": by_type,
        }
