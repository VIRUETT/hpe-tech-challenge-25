# src/orchestrator/services/emergency_service.py

from datetime import datetime, UTC

from src.models.dispatch import Dispatch, VehicleStatusSnapshot
from src.models.emergency import Emergency, EmergencyStatus
from src.orchestrator.dispatch_engine import DispatchEngine


# Emergencies that stay in DISPATCHING longer than this are cancelled (no units found).
EMERGENCY_DISPATCH_TIMEOUT_MINUTES = 10
# Emergencies that stay DISPATCHED/IN_PROGRESS longer than this are auto-resolved.
EMERGENCY_MAX_DURATION_MINUTES = 30


class EmergencyService:
    def __init__(self, fleet: dict[str, VehicleStatusSnapshot]) -> None:
        """
        Initialize the EmergencyService with a reference to the live fleet state.
        """
        self.emergencies: dict[str, Emergency] = {}
        self.dispatches: dict[str, Dispatch] = {}
        
        # Fleet reference to select units
        self.dispatch_engine = DispatchEngine(fleet)

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
            emergency.dispatched_at = datetime.now(UTC)
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
        emergency.resolved_at = datetime.now(UTC)

        # Release units via the Dispatch Engine
        return self.dispatch_engine.release_units(emergency_id)

    def get_dispatching_emergencies(self) -> list[Emergency]:
        """
        Return a list of emergencies that are waiting for available units.
        """
        return [
            e for e in self.emergencies.values() 
            if e.status == EmergencyStatus.DISPATCHING
        ]

    def evaluate_stale_emergencies(self) -> tuple[list[Emergency], list[Emergency]]:
        """
        Evaluate emergencies for timeout rules.
        Returns two lists: (emergencies_to_cancel, emergencies_to_resolve)
        """
        to_cancel = []
        to_resolve = []
        now = datetime.now(UTC)

        for emergency in self.emergencies.values():
            age_minutes = (now - emergency.created_at).total_seconds() / 60.0

            if emergency.status == EmergencyStatus.DISPATCHING:
                if age_minutes >= EMERGENCY_DISPATCH_TIMEOUT_MINUTES:
                    emergency.status = EmergencyStatus.CANCELLED
                    to_cancel.append(emergency)

            elif emergency.status in (EmergencyStatus.DISPATCHED, EmergencyStatus.IN_PROGRESS):
                if age_minutes >= EMERGENCY_MAX_DURATION_MINUTES:
                    to_resolve.append(emergency)

        return to_cancel, to_resolve