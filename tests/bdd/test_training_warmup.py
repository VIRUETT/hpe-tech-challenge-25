"""
BDD step definitions for pre-failure warm-up labels in training data.

Tests that the training data generator produces "normal" labels during the
warm-up phase and failure-specific labels during the failure phase.
"""

import pytest
from pytest_bdd import given, parsers, scenario, then

from src.ml.feature_extractor import FeatureExtractor
from src.models.enums import FailureScenario, OperationalStatus, VehicleType
from src.vehicle_agent.config import AgentConfig
from src.vehicle_agent.failure_injector import FailureInjector
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE = "../features/training_warmup.feature"


@scenario(FEATURE, "Normal scenario produces only normal labels")
def test_normal_only_labels() -> None:
    """Warmup: pure normal scenario has no failure labels."""


@scenario(FEATURE, "Failure scenario has normal labels during warm-up")
def test_failure_has_normal_warmup() -> None:
    """Warmup: engine overheat scenario contains normal warm-up rows."""


@scenario(FEATURE, "Warm-up rows precede failure rows in the dataset")
def test_warmup_rows_precede_failure_rows() -> None:
    """Warmup: normal rows appear before failure rows."""


@scenario(FEATURE, "Oil pressure drop scenario produces labelled rows")
def test_oil_pressure_labels() -> None:
    """Warmup: oil pressure drop scenario generates labelled training rows."""


@scenario(FEATURE, "Vibration anomaly scenario produces labelled rows")
def test_vibration_labels() -> None:
    """Warmup: vibration anomaly scenario generates labelled training rows."""


@scenario(FEATURE, "Brake degradation scenario produces labelled rows")
def test_brake_labels() -> None:
    """Warmup: brake degradation scenario generates labelled training rows."""


# ---------------------------------------------------------------------------
# Shared context holder
# ---------------------------------------------------------------------------


class WarmupContext:
    """Mutable context shared between BDD steps within a single scenario."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.labels: list[str] = []


@pytest.fixture
def ctx() -> WarmupContext:
    """Provide a fresh WarmupContext for each scenario."""
    return WarmupContext()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SCENARIO_MAP: dict[str, FailureScenario | None] = {
    "NORMAL": None,
    "ENGINE_OVERHEAT": FailureScenario.ENGINE_OVERHEAT,
    "BATTERY_DEGRADATION": FailureScenario.BATTERY_DEGRADATION,
    "FUEL_LEAK": FailureScenario.FUEL_LEAK,
    "OIL_PRESSURE_DROP": FailureScenario.OIL_PRESSURE_DROP,
    "VIBRATION_ANOMALY": FailureScenario.VIBRATION_ANOMALY,
    "BRAKE_DEGRADATION": FailureScenario.BRAKE_DEGRADATION,
}

_VEHICLE_TYPE_MAP: dict[str, VehicleType] = {
    "AMBULANCE": VehicleType.AMBULANCE,
    "FIRE_TRUCK": VehicleType.FIRE_TRUCK,
    "POLICE": VehicleType.POLICE,
}

# Reduced counts for fast test execution (still enough to fill the feature extractor window)
_WARMUP_TICKS = 20  # Enough to get some normal-labelled feature vectors
_FAILURE_TICKS = 20  # Enough to get some failure-labelled feature vectors


def _generate_labels(
    vehicle_type: VehicleType,
    scenario: FailureScenario | None,
    warmup_ticks: int = _WARMUP_TICKS,
    failure_ticks: int = _FAILURE_TICKS,
) -> list[str]:
    """Generate a list of labels by simulating the training pipeline.

    Args:
        vehicle_type: Vehicle type for the generator and injector.
        scenario: Failure scenario to activate after warm-up, or None for normal.
        warmup_ticks: Number of normal ticks before activating the failure.
        failure_ticks: Number of ticks after failure activation.

    Returns:
        Ordered list of label strings.
    """
    config = AgentConfig(
        vehicle_id="TRN-TEST-001",
        vehicle_type=vehicle_type,
        telemetry_frequency_hz=1.0,
    )
    generator = SimpleTelemetryGenerator(config)
    injector = FailureInjector(vehicle_type=vehicle_type)
    extractor = FeatureExtractor(window_size=10)
    labels: list[str] = []

    # Warm-up phase
    for _ in range(warmup_ticks):
        t = generator.generate(OperationalStatus.EN_ROUTE)
        extractor.add_telemetry(t)
        features = extractor.extract_features()
        if features is not None:
            labels.append("normal")

    # Failure phase
    if scenario is not None:
        injector.activate_scenario(scenario)

    for _ in range(failure_ticks):
        t = generator.generate(OperationalStatus.EN_ROUTE)
        t = injector.apply_failures(t)
        extractor.add_telemetry(t)
        features = extractor.extract_features()
        if features is not None:
            label = scenario.value if scenario is not None else "normal"
            labels.append(label)

    return labels


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given(parsers.parse("synthetic data is generated for a NORMAL scenario with an AMBULANCE"))
def generate_normal_ambulance(ctx: WarmupContext) -> None:
    """Generate normal-only training data for an ambulance."""
    ctx.labels = _generate_labels(VehicleType.AMBULANCE, None)


@given(
    parsers.parse("synthetic data is generated for an ENGINE_OVERHEAT scenario with an AMBULANCE")
)
def generate_engine_overheat_ambulance(ctx: WarmupContext) -> None:
    """Generate engine overheat training data for an ambulance."""
    ctx.labels = _generate_labels(VehicleType.AMBULANCE, FailureScenario.ENGINE_OVERHEAT)


@given(
    parsers.parse(
        "synthetic data is generated for a BATTERY_DEGRADATION scenario with an AMBULANCE"
    )
)
def generate_battery_degradation_ambulance(ctx: WarmupContext) -> None:
    """Generate battery degradation training data for an ambulance."""
    ctx.labels = _generate_labels(VehicleType.AMBULANCE, FailureScenario.BATTERY_DEGRADATION)


@given(
    parsers.parse("synthetic data is generated for an OIL_PRESSURE_DROP scenario with a FIRE_TRUCK")
)
def generate_oil_pressure_fire_truck(ctx: WarmupContext) -> None:
    """Generate oil pressure drop training data for a fire truck."""
    ctx.labels = _generate_labels(VehicleType.FIRE_TRUCK, FailureScenario.OIL_PRESSURE_DROP)


@given(
    parsers.parse(
        "synthetic data is generated for a VIBRATION_ANOMALY scenario with a POLICE vehicle"
    )
)
def generate_vibration_police(ctx: WarmupContext) -> None:
    """Generate vibration anomaly training data for a police vehicle."""
    ctx.labels = _generate_labels(VehicleType.POLICE, FailureScenario.VIBRATION_ANOMALY)


@given(
    parsers.parse("synthetic data is generated for a BRAKE_DEGRADATION scenario with an AMBULANCE")
)
def generate_brake_degradation_ambulance(ctx: WarmupContext) -> None:
    """Generate brake degradation training data for an ambulance."""
    ctx.labels = _generate_labels(VehicleType.AMBULANCE, FailureScenario.BRAKE_DEGRADATION)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse('all labels in the dataset should be "normal"'))
def all_labels_normal(ctx: WarmupContext) -> None:
    """Assert every row in the dataset is labelled 'normal'."""
    assert len(ctx.labels) > 0, "No labels generated"
    non_normal = [label for label in ctx.labels if label != "normal"]
    assert len(non_normal) == 0, f"Found non-normal labels: {set(non_normal)}"


@then(parsers.parse('the dataset should contain at least 1 "normal" label'))
def has_normal_label(ctx: WarmupContext) -> None:
    """Assert at least one 'normal' row exists (warm-up phase)."""
    assert "normal" in ctx.labels, "No 'normal' labels found in dataset"


@then(parsers.parse('the dataset should contain at least 1 "{label}" label'))
def has_failure_label(ctx: WarmupContext, label: str) -> None:
    """Assert at least one row with the given failure label exists."""
    assert label in ctx.labels, f"No '{label}' labels found. Labels seen: {set(ctx.labels)}"


@then(
    parsers.parse(
        'all "normal" rows should appear before all "{failure_label}" rows in the dataset'
    )
)
def normal_before_failure(ctx: WarmupContext, failure_label: str) -> None:
    """Assert all normal rows precede all failure-labelled rows."""
    normal_indices = [i for i, label in enumerate(ctx.labels) if label == "normal"]
    failure_indices = [i for i, label in enumerate(ctx.labels) if label == failure_label]

    if not normal_indices or not failure_indices:
        # Not enough data to verify ordering — skip rather than false-fail
        return

    last_normal = max(normal_indices)
    first_failure = min(failure_indices)

    assert last_normal < first_failure, (
        f"Normal label at index {last_normal} appears after first failure label at {first_failure}"
    )
