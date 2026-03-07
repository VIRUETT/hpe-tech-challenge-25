"""
BDD step definitions for ML predictor predict_proba real probabilities.

Tests that Predictor derives failure_probability and confidence from the model's
predict_proba output rather than returning hard-coded constants.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import numpy as np
import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.ml.predictor import Predictor
from src.models.enums import AlertSeverity, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import VEHICLE_BASELINES

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/ml_predict_proba.feature"


@scenario(FEATURE, "Predictor failure_probability is derived from predict_proba output")
def test_failure_probability_from_proba() -> None:
    """Proba: failure_probability equals the predict_proba value."""


@scenario(FEATURE, "Predictor confidence is capped at 0.99")
def test_confidence_cap() -> None:
    """Proba: confidence is capped at 0.99."""


@scenario(FEATURE, "Predictor confidence has a minimum floor of 0.50")
def test_confidence_floor() -> None:
    """Proba: confidence is floored at 0.50."""


@scenario(FEATURE, "Normal prediction produces no alerts")
def test_normal_no_alerts() -> None:
    """Proba: 'normal' prediction yields empty alert list."""


@scenario(FEATURE, "Engine overheat prediction produces a CRITICAL alert")
def test_engine_overheat_critical() -> None:
    """Proba: engine_overheat prediction produces CRITICAL alert."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class ProbaContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.predictor: Predictor | None = None  # type: ignore[name-defined]
        self.mock_model: MagicMock | None = None
        self.predicted_class: str = "normal"
        self.predicted_proba: float = 0.5
        self.alerts: list = []


@pytest.fixture
def ctx() -> ProbaContext:
    """Provide a fresh ProbaContext for each scenario."""
    return ProbaContext()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_telemetry() -> VehicleTelemetry:
    """Build a baseline ambulance telemetry record."""
    baselines = VEHICLE_BASELINES[VehicleType.AMBULANCE]
    return VehicleTelemetry(
        vehicle_id="TEST-AMB-001",
        timestamp=datetime.now(UTC),
        latitude=37.7749,
        longitude=-122.4194,
        speed_kmh=0.0,
        odometer_km=baselines["odometer_km"],
        engine_temp_celsius=baselines["engine_temp_celsius"],
        battery_voltage=baselines["battery_voltage"],
        fuel_level_percent=baselines["fuel_level_percent"],
        oil_pressure_bar=baselines["oil_pressure_bar"],
        vibration_ms2=baselines["vibration_ms2"],
        brake_pad_mm=baselines["brake_pad_mm"],
    )


def _build_mock_model(predicted_class: str, proba_value: float) -> MagicMock:
    """Build a mock RandomForest model returning controlled predict / predict_proba outputs.

    Args:
        predicted_class: Class label the model should predict.
        proba_value: Probability value for the predicted class.

    Returns:
        MagicMock that behaves like a fitted sklearn estimator.
    """
    classes = [
        "battery_degradation",
        "brake_degradation",
        "engine_overheat",
        "fuel_leak",
        "normal",
        "oil_pressure_drop",
        "vibration_anomaly",
    ]
    model = MagicMock()
    model.classes_ = classes
    model.predict.return_value = [predicted_class]
    # Build proba array: set predicted_class prob to proba_value, share remainder
    remainder = (1.0 - proba_value) / max(1, len(classes) - 1)
    proba_row = [remainder] * len(classes)
    if predicted_class in classes:
        proba_row[classes.index(predicted_class)] = proba_value
    model.predict_proba.return_value = np.array([proba_row])
    return model


def _make_predictor_with_full_window(mock_model: MagicMock) -> "Predictor":
    """Create a Predictor whose feature window is already full.

    Args:
        mock_model: The mock model to inject.

    Returns:
        Predictor instance with 10 telemetry readings pre-loaded.
    """

    predictor = Predictor.__new__(Predictor)
    predictor.vehicle_id = "TEST-AMB-001"
    from src.ml.feature_extractor import TelemetryFeatureExtractor

    predictor.extractor = TelemetryFeatureExtractor(window_size=10)
    predictor.model = mock_model
    predictor._classes = list(mock_model.classes_)

    # Fill the sliding window so extract_features() returns a result
    for _ in range(10):
        predictor.extractor.add_telemetry(_make_telemetry())

    return predictor


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a trained mock RandomForest model with predict_proba returning {proba:f} for a class"
    )
)
def mock_model_with_proba(ctx: ProbaContext, proba: float) -> None:
    """Create a mock model that returns a specific probability for a failure class."""
    ctx.predicted_class = "engine_overheat"
    ctx.predicted_proba = proba
    ctx.mock_model = _build_mock_model(ctx.predicted_class, proba)


@given('a trained mock RandomForest model that always predicts "normal"')
def mock_model_predicts_normal(ctx: ProbaContext) -> None:
    """Create a mock model that always predicts 'normal'."""
    ctx.predicted_class = "normal"
    ctx.predicted_proba = 0.9
    ctx.mock_model = _build_mock_model("normal", 0.9)


@given(
    parsers.parse(
        'a trained mock RandomForest model that predicts "engine_overheat" with probability {proba:f}'
    )
)
def mock_model_engine_overheat(ctx: ProbaContext, proba: float) -> None:
    """Create a mock model that predicts engine_overheat with a given probability."""
    ctx.predicted_class = "engine_overheat"
    ctx.predicted_proba = proba
    ctx.mock_model = _build_mock_model("engine_overheat", proba)


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("the Predictor analyzes telemetry and the model predicts that class")
def predictor_analyzes_telemetry(ctx: ProbaContext) -> None:
    """Run the predictor with the mock model and record resulting alerts."""
    assert ctx.mock_model is not None
    predictor = _make_predictor_with_full_window(ctx.mock_model)
    ctx.alerts = predictor.analyze(_make_telemetry())


@when("the Predictor analyzes telemetry with a full feature window")
def predictor_analyzes_with_full_window(ctx: ProbaContext) -> None:
    """Run the predictor with the mock model and a pre-filled feature window."""
    assert ctx.mock_model is not None
    predictor = _make_predictor_with_full_window(ctx.mock_model)
    ctx.alerts = predictor.analyze(_make_telemetry())


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the resulting alert failure_probability should equal {expected:f}"))
def alert_failure_probability_equals(ctx: ProbaContext, expected: float) -> None:
    """Assert the alert's failure_probability matches the expected value."""
    assert len(ctx.alerts) > 0, "No alerts were produced"
    actual = ctx.alerts[0].failure_probability
    assert abs(actual - expected) < 1e-9, f"failure_probability {actual} != {expected}"


@then(parsers.parse("the resulting alert confidence should be less than or equal to {threshold:f}"))
def alert_confidence_lte(ctx: ProbaContext, threshold: float) -> None:
    """Assert the alert's confidence does not exceed the cap."""
    assert len(ctx.alerts) > 0, "No alerts were produced"
    assert ctx.alerts[0].confidence <= threshold, (
        f"confidence {ctx.alerts[0].confidence} > {threshold}"
    )


@then(
    parsers.parse("the resulting alert confidence should be greater than or equal to {threshold:f}")
)
def alert_confidence_gte(ctx: ProbaContext, threshold: float) -> None:
    """Assert the alert's confidence is at least the floor value."""
    assert len(ctx.alerts) > 0, "No alerts were produced"
    assert ctx.alerts[0].confidence >= threshold, (
        f"confidence {ctx.alerts[0].confidence} < {threshold}"
    )


@then("no alerts should be produced")
def no_alerts_produced(ctx: ProbaContext) -> None:
    """Assert the alert list is empty."""
    assert ctx.alerts == [], f"Expected no alerts, got {ctx.alerts}"


@then("a CRITICAL severity alert should be produced")
def critical_alert_produced(ctx: ProbaContext) -> None:
    """Assert at least one CRITICAL severity alert was produced."""
    assert len(ctx.alerts) > 0, "No alerts were produced"
    severities = [a.severity for a in ctx.alerts]
    assert AlertSeverity.CRITICAL in severities, (
        f"No CRITICAL alert found; severities: {severities}"
    )


@then(parsers.parse("the alert failure_probability should equal {expected:f}"))
def alert_failure_probability_equals_v2(ctx: ProbaContext, expected: float) -> None:
    """Assert the first alert's failure_probability matches the expected value."""
    assert len(ctx.alerts) > 0, "No alerts were produced"
    actual = ctx.alerts[0].failure_probability
    assert abs(actual - expected) < 1e-9, f"failure_probability {actual} != {expected}"
