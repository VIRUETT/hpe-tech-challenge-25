# src/orchestrator/services/emergency_service.py

from datetime import datetime, timedelta

from src.core.time import Clock, RealClock
from src.models.dispatch import Dispatch, VehicleStatusSnapshot
from src.models.emergency import Emergency, EmergencySeverity, EmergencyStatus, EmergencyType
from src.orchestrator.dispatch_engine import DispatchEngine

# Emergencies that stay in DISPATCHING longer than this are cancelled (no units found).
EMERGENCY_DISPATCH_TIMEOUT_MINUTES = 10
# Emergencies that stay DISPATCHED too long without progress are auto-dismissed.
EMERGENCY_DISPATCHED_STALL_TIMEOUT_MINUTES = 25

# Base handling duration (minutes) per emergency type at MODERATE severity.
EMERGENCY_BASE_DURATION_MINUTES: dict[EmergencyType, int] = {
    EmergencyType.MEDICAL: 18,
    EmergencyType.FIRE: 28,
    EmergencyType.CRIME: 15,
    EmergencyType.ACCIDENT: 22,
    EmergencyType.HAZMAT: 35,
    EmergencyType.RESCUE: 30,
    EmergencyType.NATURAL_DISASTER: 45,
}

# Severity scales expected handling duration similarly to operational complexity.
DURATION_SEVERITY_MULTIPLIERS: dict[int, float] = {
    EmergencySeverity.LOW.value: 0.75,
    EmergencySeverity.MODERATE.value: 1.0,
    EmergencySeverity.HIGH.value: 1.25,
    EmergencySeverity.SEVERE.value: 1.5,
    EmergencySeverity.CRITICAL.value: 1.75,
}


class EmergencyService:
    def __init__(
        self, fleet: dict[str, VehicleStatusSnapshot], *, clock: Clock | None = None
    ) -> None:
        """
        Initialize the EmergencyService with a reference to the live fleet state.
        """
        self._clock = clock or RealClock()
        self.emergencies: dict[str, Emergency] = {}
        self.dispatches: dict[str, Dispatch] = {}

        # Fleet reference to select units
        self.dispatch_engine = DispatchEngine(fleet)

    def _planned_duration_minutes(self, emergency: Emergency) -> float:
        """Estimate expected on-scene duration based on type, severity, and scale."""
        base = EMERGENCY_BASE_DURATION_MINUTES.get(emergency.emergency_type, 20)
        severity_multiplier = DURATION_SEVERITY_MULTIPLIERS.get(emergency.severity.value, 1.0)

        unit_scale = max(1, emergency.units_required.total)
        multi_unit_multiplier = 1.0 + 0.1 * (unit_scale - 1)

        planned = base * severity_multiplier * multi_unit_multiplier
        return max(8.0, planned)

    def _max_duration_minutes(self, emergency: Emergency) -> float:
        """Return hard timeout for in-progress incidents before forced dismissal."""
        return self._planned_duration_minutes(emergency) * 1.4

    def process_emergency(self, emergency: Emergency) -> Dispatch:
        """
        Core domain logic for processing a new emergency.
        Stores it, runs the dispatch engine, and updates statuses.
        """
        self.emergencies[emergency.emergency_id] = emergency

        # Delegate unit selection to the Dispatch Engine
        dispatch = self.dispatch_engine.select_units(emergency)
        self.dispatches[emergency.emergency_id] = dispatch

        if dispatch.units:
            emergency.status = EmergencyStatus.DISPATCHED
            emergency.dispatched_at = self._clock.now()
        else:
            emergency.status = EmergencyStatus.DISPATCHING

        return dispatch

    def resolve_emergency(self, emergency_id: str) -> list[str]:
        """
        Mark an emergency as resolved and release its units back to IDLE.
        """
        if emergency_id not in self.emergencies:
            raise KeyError(f"Emergency {emergency_id} not found.")

        emergency = self.emergencies[emergency_id]
        emergency.status = EmergencyStatus.RESOLVED
        emergency.resolved_at = self._clock.now()

        # Release units via the Dispatch Engine
        return self.dispatch_engine.release_units(emergency_id)

    def dismiss_emergency(self, emergency_id: str) -> list[str]:
        """Mark an emergency as dismissed and release its units back to IDLE."""
        if emergency_id not in self.emergencies:
            raise KeyError(f"Emergency {emergency_id} not found.")

        emergency = self.emergencies[emergency_id]
        emergency.status = EmergencyStatus.DISMISSED
        emergency.dismissed_at = self._clock.now()

        return self.dispatch_engine.release_units(emergency_id)

    def mark_emergency_in_progress(self, emergency_id: str) -> bool:
        """Mark emergency as IN_PROGRESS once at least one assigned unit arrives."""
        emergency = self.emergencies.get(emergency_id)
        if emergency is None:
            return False

        if emergency.status != EmergencyStatus.DISPATCHED:
            return False

        emergency.status = EmergencyStatus.IN_PROGRESS
        return True

    def get_dispatching_emergencies(self) -> list[Emergency]:
        """
        Return a list of emergencies that are waiting for available units.
        """
        return [e for e in self.emergencies.values() if e.status == EmergencyStatus.DISPATCHING]

    def evaluate_stale_emergencies(
        self,
    ) -> tuple[list[Emergency], list[Emergency], list[Emergency]]:
        """
        Evaluate emergencies for timeout rules.
        Returns three lists:
        (emergencies_to_cancel, emergencies_to_auto_resolve, emergencies_to_dismiss)
        """
        to_cancel: list[Emergency] = []
        to_auto_resolve: list[Emergency] = []
        to_dismiss: list[Emergency] = []
        now = self._clock.now()

        for emergency in self.emergencies.values():
            # Historical playback emergencies are lifecycle-managed by
            # HistoricalCrimeInjector using simulated-time rules.
            if emergency.reported_by == "historical_playback":
                continue

            age_minutes = (now - emergency.created_at).total_seconds() / 60.0

            if emergency.status == EmergencyStatus.DISPATCHING:
                if age_minutes >= EMERGENCY_DISPATCH_TIMEOUT_MINUTES:
                    emergency.status = EmergencyStatus.CANCELLED
                    to_cancel.append(emergency)

            elif emergency.status == EmergencyStatus.DISPATCHED:
                if emergency.dispatched_at is None:
                    continue
                dispatched_minutes = (now - emergency.dispatched_at).total_seconds() / 60.0
                if dispatched_minutes >= EMERGENCY_DISPATCHED_STALL_TIMEOUT_MINUTES:
                    to_dismiss.append(emergency)

            elif emergency.status == EmergencyStatus.IN_PROGRESS:
                if emergency.dispatched_at is None:
                    continue

                on_mission_minutes = (now - emergency.dispatched_at).total_seconds() / 60.0
                planned_minutes = self._planned_duration_minutes(emergency)

                if on_mission_minutes >= self._max_duration_minutes(emergency):
                    to_dismiss.append(emergency)
                elif on_mission_minutes >= planned_minutes:
                    to_auto_resolve.append(emergency)

        return to_cancel, to_auto_resolve, to_dismiss

    def expected_resolution_eta(self, emergency_id: str) -> datetime | None:
        """Return estimated resolution timestamp for a dispatched/in-progress emergency."""
        emergency = self.emergencies.get(emergency_id)
        if emergency is None or emergency.dispatched_at is None:
            return None

        return emergency.dispatched_at + timedelta(
            minutes=self._planned_duration_minutes(emergency)
        )
