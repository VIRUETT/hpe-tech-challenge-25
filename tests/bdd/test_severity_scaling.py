"""
BDD step definitions for severity-scaled emergency unit dispatch.

Tests that scale_units_by_severity() produces the correct unit counts
for each severity level.
"""

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from src.models.emergency import EmergencySeverity, UnitsRequired, scale_units_by_severity

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/severity_scaling.feature"


@scenario(FEATURE, "LOW severity halves the unit count (minimum 1)")
def test_low_severity() -> None:
    """Scaling: LOW severity gives minimum 1 of each required type."""


@scenario(FEATURE, "MODERATE severity keeps the baseline count")
def test_moderate_severity() -> None:
    """Scaling: MODERATE severity is unchanged from baseline."""


@scenario(FEATURE, "HIGH severity adds 50% more units")
def test_high_severity() -> None:
    """Scaling: HIGH severity scales by 1.5×."""


@scenario(FEATURE, "SEVERE severity doubles the unit count")
def test_severe_severity() -> None:
    """Scaling: SEVERE severity scales by 2×."""


@scenario(FEATURE, "CRITICAL severity triples the unit count")
def test_critical_severity() -> None:
    """Scaling: CRITICAL severity scales by 3×."""


@scenario(FEATURE, "Zero count vehicle types remain zero regardless of severity")
def test_zero_types_remain_zero() -> None:
    """Scaling: zero-count vehicle types stay zero even at CRITICAL severity."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class ScalingContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.base: UnitsRequired | None = None
        self.result: UnitsRequired | None = None


@pytest.fixture
def ctx() -> ScalingContext:
    """Provide a fresh ScalingContext for each scenario."""
    return ScalingContext()


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a baseline of {amb:d} ambulances, {fire:d} fire trucks, and {pol:d} police units"
    )
)
def set_baseline(ctx: ScalingContext, amb: int, fire: int, pol: int) -> None:
    """Set the baseline UnitsRequired for the scenario."""
    ctx.base = UnitsRequired(ambulances=amb, fire_trucks=fire, police=pol)


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


_SEVERITY_MAP: dict[str, EmergencySeverity] = {
    "LOW": EmergencySeverity.LOW,
    "MODERATE": EmergencySeverity.MODERATE,
    "HIGH": EmergencySeverity.HIGH,
    "SEVERE": EmergencySeverity.SEVERE,
    "CRITICAL": EmergencySeverity.CRITICAL,
}


@when(parsers.parse("the units are scaled by {severity_name} severity"))
def scale_units(ctx: ScalingContext, severity_name: str) -> None:
    """Apply scale_units_by_severity with the given severity level."""
    assert ctx.base is not None
    severity = _SEVERITY_MAP[severity_name]
    ctx.result = scale_units_by_severity(ctx.base, severity)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the result should have {expected:d} ambulance"))
@then(parsers.parse("the result should have {expected:d} ambulances"))
def result_ambulances(ctx: ScalingContext, expected: int) -> None:
    """Assert the scaled ambulance count matches expected."""
    assert ctx.result is not None
    assert ctx.result.ambulances == expected, (
        f"Expected {expected} ambulances, got {ctx.result.ambulances}"
    )


@then(parsers.parse("the result should have {expected:d} fire_truck"))
@then(parsers.parse("the result should have {expected:d} fire_trucks"))
def result_fire_trucks(ctx: ScalingContext, expected: int) -> None:
    """Assert the scaled fire truck count matches expected."""
    assert ctx.result is not None
    assert ctx.result.fire_trucks == expected, (
        f"Expected {expected} fire trucks, got {ctx.result.fire_trucks}"
    )


@then(parsers.parse("the result should have {expected:d} police"))
def result_police(ctx: ScalingContext, expected: int) -> None:
    """Assert the scaled police count matches expected."""
    assert ctx.result is not None
    assert ctx.result.police == expected, f"Expected {expected} police, got {ctx.result.police}"
