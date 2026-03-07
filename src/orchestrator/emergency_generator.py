"""
AI-driven emergency generation system for Project AEGIS.

Provides real-time predictive analytics using the Random Forest crime model.
"""

import asyncio
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
from src.ml.predictor import CrimePredictor

logger = structlog.get_logger(__name__)


class EmergencyGenerator:
    """Generates emergencies based on AI predictions across city neighborhoods."""

    def __init__(
        self,
        orchestrator: OrchestratorAgent,
        check_interval_seconds: float = 300.0,  # Scan the city every 5 minutes
    ) -> None:
        """
        Initialize the predictive emergency generator.

        Args:
            orchestrator: The orchestrator to submit emergencies to.
            check_interval_seconds: How often to run the ML model inference.
        """
        self.orchestrator = orchestrator
        self.check_interval_seconds = check_interval_seconds
        self.running = False
        
        # Load the ML Predictor
        self.predictor = CrimePredictor(confidence_threshold=0.90)
        
        # Track active alerts to prevent spamming the dispatch engine
        # with the same neighborhood every loop.
        self.active_predictions: set[str] = set()

    async def start(self) -> None:
        """Start the ML generation loop."""
        self.running = True
        logger.info("predictive_generator_started", interval=self.check_interval_seconds)

        while self.running:
            try:
                await self._generate_predictive_emergencies()
            except Exception as e:
                logger.error("predictive_generator_error", error=str(e), exc_info=True)

            await asyncio.sleep(self.check_interval_seconds)

    def stop(self) -> None:
        """Stop the generation loop."""
        self.running = False
        logger.info("predictive_generator_stopped")

    async def _generate_predictive_emergencies(self) -> None:
        """Run inference and submit emergencies for high-risk areas."""
        if not self.predictor.is_ready:
            return

        current_time = datetime.now()
        recommendations = self.predictor.predict_current_risk(current_time)

        # Track which neighborhoods are currently in a high-risk state
        current_high_risk_neighborhoods = {rec['neighborhood'] for rec in recommendations}

        # Clear out old predictions from our cache if they are no longer high-risk
        self.active_predictions = self.active_predictions.intersection(current_high_risk_neighborhoods)

        for rec in recommendations:
            neighborhood = rec['neighborhood']
            
            # Skip if we already dispatched units here recently
            if neighborhood in self.active_predictions:
                continue

            prob = rec['risk_probability']
            
            # Map the ML probability to AEGIS Severity Levels
            # > 95% = CRITICAL (5), > 90% = SEVERE (4)
            severity = EmergencySeverity.CRITICAL if prob > 0.95 else EmergencySeverity.SEVERE

            # Create strict GPS Location object
            location = Location(
                latitude=rec['latitude'], 
                longitude=rec['longitude'], 
                timestamp=datetime.now(UTC)
            )

            # Define as a CRIME and calculate required units (Police)
            em_type = EmergencyType.CRIME
            units_required = scale_units_by_severity(EMERGENCY_UNITS_DEFAULTS[em_type], severity)

            # Build the AEGIS Emergency model
            emergency = Emergency(
                emergency_type=em_type,
                severity=severity,
                location=location,
                address=neighborhood,
                description=f"AI Prediction: High risk of {rec['common_crime_type']} ({prob:.1%} confidence)",
                units_required=units_required,
                reported_by="ai_crime_predictor",
            )

            logger.info("ai_dispatching_emergency", neighborhood=neighborhood, probability=prob, severity=severity.value)

            # Send to the dispatch engine
            await self.orchestrator.process_emergency(emergency)
            
            # Mark as active so we don't spam it
            self.active_predictions.add(neighborhood)