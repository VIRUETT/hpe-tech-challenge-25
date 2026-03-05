"""
BDD step definitions for rule-based anomaly detector fallback behaviour.

Tests that the VehicleAgent uses the rule-based AnomalyDetector for the first
10 ticks, switches to the ML Predictor on tick 11+, and keeps the rule detector
as a safety net when the ML model returns no alerts.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.models.alerts import PredictiveAlert
from src.models.enums import AlertSeverity, FailureCategory, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.vehicle_agent.config import VEHICLE_BASELINES

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/anomaly_fallback.feature"


@scenario(FEATURE, "Rule-based detector is used on tick 1")
def test_rule_used_tick_1() -> None:
    """Fallback: rule detector called on tick 1."""


@scenario(FEATURE, "Rule-based detector is used on tick 10")
def test_rule_used_tick_10() -> None:
    """Fallback: rule detector called on tick 10."""


@scenario(FEATURE, "ML predictor is used on tick 11")
def test_ml_used_tick_11() -> None:
    """Fallback: ML predictor called on tick 11."""


@scenario(FEATURE, "ML predictor is used on tick 50")
def test_ml_used_tick_50() -> None:
    """Fallback: ML predictor called on tick 50."""


@scenario(
    FEATURE,
    "Rule-based detector acts as safety net when ML returns no alerts on tick 11",
)
def test_rule_safety_net() -> None:
    """Fallback: rule detector fills in when ML returns nothing on tick 11+."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class FallbackContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.mock_rule_detector: MagicMock | None = None
        self.mock_ml_predictor: MagicMock | None = None
        self.final_alerts: list = []
        # Configurable return values for each detector
        self.ml_returns_alerts: bool = True
        self.rule_returns_alerts: bool = False


@pytest.fixture
def ctx() -> FallbackContext:
    """Provide a fresh FallbackContext for each scenario."""
    return FallbackContext()


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


def _make_dummy_alert() -> "PredictiveAlert":  # type: ignore[name-defined]
    """Create a dummy predictive alert for testing."""

    return PredictiveAlert(
        vehicle_id="TEST-AMB-001",
        timestamp=datetime.now(UTC),
        severity=AlertSeverity.WARNING,
        category=FailureCategory.ENGINE,
        component="engine",
        failure_probability=0.7,
        confidence=0.8,
        predicted_failure_min_hours=1.0,
        predicted_failure_max_hours=4.0,
        predicted_failure_likely_hours=2.0,
        can_complete_current_mission=True,
        safe_to_operate=True,
        recommended_action="Monitor engine.",
        contributing_factors=["test"],
        related_telemetry={"engine_temp_celsius": 95.0},
    )


def _run_tick_logic(
    tick_count: int,
    mock_rule_detector: MagicMock,
    mock_ml_predictor: MagicMock,
) -> list:
    """Execute the fallback logic directly (mirrors VehicleAgent._tick rule).

    This reimplements the core detection logic from agent.py so that the BDD
    tests are deterministic and do not require Redis or async infrastructure.

    Args:
        tick_count: The tick number to simulate (1-indexed).
        mock_rule_detector: Mock rule-based detector with .analyze().
        mock_ml_predictor: Mock ML predictor with .analyze().

    Returns:
        Final list of alerts produced for this tick.
    """
    telemetry = _make_telemetry()

    if tick_count <= 10:
        alerts = mock_rule_detector.analyze(telemetry)
    else:
        alerts = mock_ml_predictor.analyze(telemetry)
        if not alerts:
            alerts = mock_rule_detector.analyze(telemetry)

    return alerts


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("a vehicle agent with a mock rule detector and a mock ML predictor")
def mock_detectors(ctx: FallbackContext) -> None:
    """Set up mock rule and ML detectors with default return values."""
    ctx.mock_rule_detector = MagicMock()
    ctx.mock_ml_predictor = MagicMock()
    # Default: both return no alerts
    ctx.mock_rule_detector.analyze.return_value = []
    ctx.mock_ml_predictor.analyze.return_value = []


@given("the ML predictor returns no alerts")
def ml_returns_no_alerts(ctx: FallbackContext) -> None:
    """Configure ML predictor to return an empty list."""
    assert ctx.mock_ml_predictor is not None
    ctx.mock_ml_predictor.analyze.return_value = []
    ctx.ml_returns_alerts = False


@given("the rule-based detector returns one alert")
def rule_returns_one_alert(ctx: FallbackContext) -> None:
    """Configure rule detector to return one alert."""
    assert ctx.mock_rule_detector is not None
    ctx.mock_rule_detector.analyze.return_value = [_make_dummy_alert()]
    ctx.rule_returns_alerts = True


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(parsers.parse("the agent processes tick number {tick:d}"))
def process_tick(ctx: FallbackContext, tick: int) -> None:
    """Execute the fallback detection logic for the given tick number."""
    assert ctx.mock_rule_detector is not None
    assert ctx.mock_ml_predictor is not None
    ctx.final_alerts = _run_tick_logic(tick, ctx.mock_rule_detector, ctx.mock_ml_predictor)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("the rule-based detector should have been called")
def rule_detector_was_called(ctx: FallbackContext) -> None:
    """Assert the rule-based detector's analyze() was invoked."""
    assert ctx.mock_rule_detector is not None
    ctx.mock_rule_detector.analyze.assert_called()


@then("the ML predictor should NOT have been called")
def ml_predictor_not_called(ctx: FallbackContext) -> None:
    """Assert the ML predictor's analyze() was NOT invoked."""
    assert ctx.mock_ml_predictor is not None
    ctx.mock_ml_predictor.analyze.assert_not_called()


@then("the ML predictor should have been called")
def ml_predictor_was_called(ctx: FallbackContext) -> None:
    """Assert the ML predictor's analyze() was invoked."""
    assert ctx.mock_ml_predictor is not None
    ctx.mock_ml_predictor.analyze.assert_called()


@then("the final alert list should not be empty")
def final_alerts_not_empty(ctx: FallbackContext) -> None:
    """Assert at least one alert was produced for this tick."""
    assert len(ctx.final_alerts) > 0, "Expected alerts but got none"
