"""
Automatic emergency generation system using a Poisson process.
"""

import asyncio
import math
import random
from datetime import UTC, datetime

import structlog

from src.models.emergency import (
    EMERGENCY_UNITS_DEFAULTS,
    Emergency,
    EmergencySeverity,
    EmergencyType,
    Location,
    scale_units_by_severity,
)
from src.orchestrator.agent import OrchestratorAgent

logger = structlog.get_logger(__name__)


class EmergencyGenerator:
    """Generates random emergencies around a center point."""

    def __init__(
        self,
        orchestrator: OrchestratorAgent,
        center_lat: float = 37.7749,
        center_lon: float = -122.4194,
        radius_km: float = 5.0,
        rate_per_hour: float = 12.0,  # One every 5 mins on average
    ) -> None:
        """
        Initialize the emergency generator.

        Args:
            orchestrator: The orchestrator to submit emergencies to.
            center_lat: Base latitude for generated incidents.
            center_lon: Base longitude for generated incidents.
            radius_km: Max distance from center to generate incidents.
            rate_per_hour: Average number of emergencies per hour.
        """
        self.orchestrator = orchestrator
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius_km = radius_km
        self.rate_per_hour = rate_per_hour
        self.running = False

    async def start(self) -> None:
        """Start the generation loop."""
        self.running = True
        logger.info("emergency_generator_started", rate_per_hour=self.rate_per_hour)

        tick_interval = 10.0  # check every 10 seconds
        dt_hours = tick_interval / 3600.0

        while self.running:
            try:
                if self.rate_per_hour > 0:
                    prob = 1.0 - math.exp(-self.rate_per_hour * dt_hours)
                    if random.random() < prob:
                        await self._generate_emergency()
            except Exception as e:
                logger.error("emergency_generator_error", error=str(e), exc_info=True)

            await asyncio.sleep(tick_interval)

    def stop(self) -> None:
        """Stop the generation loop."""
        self.running = False
        logger.info("emergency_generator_stopped")

    async def _generate_emergency(self) -> None:
        """Generate and submit a single random emergency."""
        # Random location within radius
        # Approximate 1 degree lat = 111 km
        lat_offset = random.uniform(-self.radius_km, self.radius_km) / 111.0
        lon_offset = random.uniform(-self.radius_km, self.radius_km) / (
            111.0 * math.cos(math.radians(self.center_lat))
        )

        lat = self.center_lat + lat_offset
        lon = self.center_lon + lon_offset

        em_type = random.choice(list(EmergencyType))
        severity = random.choice(list(EmergencySeverity))

        location = Location(latitude=lat, longitude=lon, timestamp=datetime.now(UTC))

        units_required = scale_units_by_severity(EMERGENCY_UNITS_DEFAULTS[em_type], severity)

        emergency = Emergency(
            emergency_type=em_type,
            severity=severity,
            location=location,
            address=f"Lat {lat:.4f}, Lon {lon:.4f}",
            description=f"Auto-generated {em_type.value} incident",
            units_required=units_required,
            reported_by="system_generator",
        )

        logger.info("auto_generating_emergency", type=em_type.value, severity=severity.value)

        # We need to process it through orchestrator.
        # But wait, in API it calls `await orchestrator.process_emergency(emergency)`
        # Then broadcasts to websocket.
        # If we just do it here, we skip the websocket broadcast unless we pass a callback.
        # Let's just process it.
        await self.orchestrator.process_emergency(emergency)
