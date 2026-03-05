"""
Machine Learning inference predictor for anomaly detection.

Uses a trained RandomForest model to detect failure precursors and generate
predictive alerts.  Failure probability and confidence values are derived from
the model's ``predict_proba`` output rather than hardcoded constants.
"""

import os
from datetime import UTC, datetime

import joblib
import numpy as np
import pandas as pd
import structlog

from src.ml.feature_extractor import FeatureExtractor
from src.models.alerts import PredictiveAlert
from src.models.enums import AlertSeverity, FailureCategory, FailureScenario
from src.models.telemetry import VehicleTelemetry

logger = structlog.get_logger(__name__)

# Mapping from failure scenario value to (FailureCategory, AlertSeverity, action, safe_to_operate)
_SCENARIO_META: dict[str, tuple[FailureCategory, AlertSeverity, str, bool]] = {
    FailureScenario.ENGINE_OVERHEAT.value: (
        FailureCategory.ENGINE,
        AlertSeverity.CRITICAL,
        "STOP IMMEDIATELY - Critical engine overheat predicted.",
        False,
    ),
    FailureScenario.BATTERY_DEGRADATION.value: (
        FailureCategory.ELECTRICAL,
        AlertSeverity.WARNING,
        "Monitor electrical system. Impending battery failure.",
        True,
    ),
    FailureScenario.FUEL_LEAK.value: (
        FailureCategory.FUEL,
        AlertSeverity.CRITICAL,
        "REFUEL IMMEDIATELY - Severe fuel leak detected.",
        False,
    ),
    FailureScenario.OIL_PRESSURE_DROP.value: (
        FailureCategory.ENGINE,
        AlertSeverity.CRITICAL,
        "STOP IMMEDIATELY - Critical oil pressure drop predicted.",
        False,
    ),
    FailureScenario.VIBRATION_ANOMALY.value: (
        FailureCategory.OTHER,
        AlertSeverity.WARNING,
        "Unusual chassis vibration. Inspect suspension and drivetrain.",
        True,
    ),
    FailureScenario.BRAKE_DEGRADATION.value: (
        FailureCategory.OTHER,
        AlertSeverity.WARNING,
        "Brake pad wear detected. Schedule inspection soon.",
        True,
    ),
}

# Predicted time-to-failure estimates per severity tier (min/likely/max hours)
_SEVERITY_TIME_TO_FAILURE: dict[AlertSeverity, tuple[float, float, float]] = {
    AlertSeverity.CRITICAL: (0.25, 0.75, 1.5),
    AlertSeverity.WARNING: (1.0, 3.0, 8.0),
    AlertSeverity.INFO: (4.0, 12.0, 24.0),
}


class Predictor:
    """Uses a trained RandomForest model to detect anomalies.

    Failure probability is derived from ``predict_proba`` class probabilities
    rather than hardcoded constants.
    """

    def __init__(self, vehicle_id: str, model_path: str = "src/ml/model.joblib") -> None:
        """
        Initialize the predictor.

        Args:
            vehicle_id: ID of the vehicle being monitored
            model_path: Path to the trained ML model
        """
        self.vehicle_id = vehicle_id
        self.extractor = FeatureExtractor(window_size=10)
        self.model = None
        self._classes: list[str] = []

        if os.path.exists(model_path):
            try:
                self.model = joblib.load(model_path)
                self._classes = list(self.model.classes_)
                logger.info("ml_model_loaded", vehicle_id=vehicle_id, path=model_path)
            except Exception as e:
                logger.error("ml_model_load_failed", error=str(e))
        else:
            logger.warning("ml_model_not_found", path=model_path, msg="Falling back to no-op")

    def analyze(self, telemetry: VehicleTelemetry) -> list[PredictiveAlert]:
        """
        Analyze telemetry using ML model.

        Args:
            telemetry: Current telemetry point

        Returns:
            List of generated predictive alerts
        """
        self.extractor.add_telemetry(telemetry)

        if self.model is None:
            return []

        features = self.extractor.extract_features()
        if not features:
            # Window not full yet
            return []

        # Predict class and probabilities
        df = pd.DataFrame([{k: v for k, v in features.items() if k != "label"}])
        prediction: str = self.model.predict(df)[0]

        # We assume labels match FailureScenario.value, plus 'normal'
        if prediction == "normal":
            return []

        # Extract real probability from predict_proba
        proba_array: np.ndarray = self.model.predict_proba(df)[0]
        proba_dict: dict[str, float] = dict(zip(self._classes, proba_array.tolist(), strict=False))
        failure_probability = float(proba_dict.get(prediction, 0.5))

        # Confidence: 1 − entropy-normalised uncertainty
        # For n classes, max entropy = log2(n). We use the predicted class probability
        # directly as a proxy for model confidence (simpler and interpretable).
        confidence = min(0.99, max(0.50, failure_probability))

        # Look up metadata for this scenario
        meta = _SCENARIO_META.get(prediction)
        if meta:
            category, severity, action, safe_to_operate = meta
        else:
            category = FailureCategory.OTHER
            severity = AlertSeverity.WARNING
            action = f"Anomaly detected: {prediction}"
            safe_to_operate = True

        ttf_min, ttf_likely, ttf_max = _SEVERITY_TIME_TO_FAILURE[severity]

        alert = PredictiveAlert(
            vehicle_id=self.vehicle_id,
            timestamp=datetime.now(UTC),
            severity=severity,
            category=category,
            component=prediction,
            failure_probability=failure_probability,
            confidence=confidence,
            predicted_failure_min_hours=ttf_min,
            predicted_failure_max_hours=ttf_max,
            predicted_failure_likely_hours=ttf_likely,
            can_complete_current_mission=safe_to_operate,
            safe_to_operate=safe_to_operate,
            recommended_action=action,
            contributing_factors=[f"ML prediction: {prediction} (p={failure_probability:.2f})"],
            related_telemetry={
                k: float(v) for k, v in features.items() if isinstance(v, (int, float))
            },
        )
        return [alert]
