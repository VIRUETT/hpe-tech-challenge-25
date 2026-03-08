"""
Dispatch engine for selecting and assigning units to emergencies.

This module implements the logic for selecting the best available vehicles
to respond to an emergency based on proximity and availability.
"""

import math

import structlog

from src.models.dispatch import Dispatch, DispatchedUnit, VehicleStatusSnapshot
from src.models.emergency import Emergency
from src.models.enums import OperationalStatus, VehicleType
from src.models.vehicle import Location

logger = structlog.get_logger(__name__)


def _haversine_km(a: Location, b: Location) -> float:
    """Calculate great-circle distance between two GPS points in kilometers.

    Uses the Haversine formula for accurate distance on a sphere.

    Args:
        a: First GPS location.
        b: Second GPS location.

    Returns:
        Distance in kilometers.
    """
    r = 6371.0  # Earth radius in km
    lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
    lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class DispatchEngine:
    """Selects the best available vehicles to respond to an emergency.

    Selection strategy (MVP):
    - Filter to available vehicles (IDLE, no active alert, correct type).
    - Sort by Haversine distance from the emergency location.
    - Pick the N closest units of each required type.

    If fewer vehicles are available than required, dispatch as many as possible
    and log a warning.

    Attributes:
        fleet: Current vehicle status snapshots keyed by vehicle_id.
    """

    def __init__(self, fleet: dict[str, VehicleStatusSnapshot]) -> None:
        """Initialize the dispatch engine with a reference to the fleet state.

        Args:
            fleet: Mutable dict of vehicle_id -> VehicleStatusSnapshot,
                   shared with the OrchestratorAgent.
        """
        self._fleet = fleet

    def select_units(self, emergency: Emergency) -> Dispatch:
        """Select and create a dispatch for the given emergency.

        Selects the nearest available units of each required type and returns
        a Dispatch object. Updates selected vehicle statuses to EN_ROUTE in-place.

        Args:
            emergency: The emergency requiring unit assignment.

        Returns:
            A Dispatch record with the assigned units.
        """
        selected_units: list[DispatchedUnit] = []

        required = emergency.units_required
        type_requirements: list[tuple[VehicleType, int]] = [
            (VehicleType.AMBULANCE, required.ambulances),
            (VehicleType.FIRE_TRUCK, required.fire_trucks),
            (VehicleType.POLICE, required.police),
        ]

        for vehicle_type, count in type_requirements:
            if count == 0:
                continue

            candidates = self._get_available_candidates(vehicle_type, emergency.location)

            if len(candidates) < count:
                logger.warning(
                    "insufficient_units",
                    emergency_id=emergency.emergency_id,
                    vehicle_type=vehicle_type.value,
                    required=count,
                    available=len(candidates),
                )

            chosen = candidates[:count]
            for snap in chosen:
                selected_units.append(
                    DispatchedUnit(
                        vehicle_id=snap.vehicle_id,
                        vehicle_type=snap.vehicle_type,
                        acknowledged_at=None,
                    )
                )
                # Mark as dispatched in the shared fleet state
                snap.operational_status = OperationalStatus.EN_ROUTE
                snap.current_emergency_id = emergency.emergency_id

                logger.info(
                    "unit_assigned",
                    vehicle_id=snap.vehicle_id,
                    emergency_id=emergency.emergency_id,
                    vehicle_type=vehicle_type.value,
                )

        dispatch = Dispatch(
            emergency_id=emergency.emergency_id,
            units=selected_units,
            selection_criteria="nearest_available",
            completed_at=None,
        )

        logger.info(
            "dispatch_created",
            dispatch_id=dispatch.dispatch_id,
            emergency_id=emergency.emergency_id,
            units_count=len(selected_units),
            vehicle_ids=dispatch.vehicle_ids,
        )

        return dispatch

    def _get_available_candidates(
        self,
        vehicle_type: VehicleType,
        location: Location,
    ) -> list[VehicleStatusSnapshot]:
        """Return available vehicles of a given type sorted by distance.

        Args:
            vehicle_type: The type of vehicle needed.
            location: Emergency location used to sort by proximity.

        Returns:
            List of available VehicleStatusSnapshot sorted nearest-first.
        """
        candidates = [
            snap
            for snap in self._fleet.values()
            if snap.vehicle_type == vehicle_type and snap.is_available and snap.location is not None
        ]

        candidates.sort(
            key=lambda s: _haversine_km(s.location, location)  # type: ignore[arg-type]
        )

        return candidates

    def release_units(self, emergency_id: str) -> list[str]:
        """Release all vehicles assigned to a resolved emergency back to IDLE.

        Args:
            emergency_id: The ID of the resolved emergency.

        Returns:
            List of vehicle_ids that were released.
        """
        released: list[str] = []

        for snap in self._fleet.values():
            if snap.current_emergency_id == emergency_id:
                snap.operational_status = OperationalStatus.IDLE
                snap.current_emergency_id = None
                released.append(snap.vehicle_id)

                logger.info(
                    "unit_released",
                    vehicle_id=snap.vehicle_id,
                    emergency_id=emergency_id,
                )

        return released

    @property
    def available_count(self) -> dict[str, int]:
        """Count of available vehicles by type.

        Returns:
            Dict mapping vehicle type string to count of available units.
        """
        counts: dict[str, int] = {}
        for snap in self._fleet.values():
            if snap.is_available:
                key = snap.vehicle_type.value
                counts[key] = counts.get(key, 0) + 1
        return counts
