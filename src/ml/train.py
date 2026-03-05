"""
Script to generate synthetic telemetry data and train a ML model for anomaly detection.

Key improvements over the original:
- Multi-vehicle-type training (ambulance, fire truck, police)
- Pre-failure warm-up: 200–500 normal ticks before activating a failure so the
  model learns the normal → onset → degradation transition.
- Covers all 6 failure scenarios including the 3 new ones.
- Fixed random seed for reproducibility.
"""

import os
import random

import joblib
import pandas as pd
import structlog
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from src.ml.feature_extractor import FeatureExtractor
from src.models.enums import FailureScenario, OperationalStatus, VehicleType
from src.vehicle_agent.config import AgentConfig
from src.vehicle_agent.failure_injector import FailureInjector
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

logger = structlog.get_logger(__name__)

# Random seed for reproducibility across training runs
RANDOM_SEED = 42

# Normal warm-up ticks before activating a failure scenario.
# Randomised per scenario so the model sees diverse transition lengths.
WARMUP_MIN = 200
WARMUP_MAX = 500

# All failure scenarios to train on
ALL_SCENARIOS: list[FailureScenario | None] = [
    None,  # Normal — no failure
    FailureScenario.ENGINE_OVERHEAT,
    FailureScenario.BATTERY_DEGRADATION,
    FailureScenario.FUEL_LEAK,
    FailureScenario.OIL_PRESSURE_DROP,
    FailureScenario.VIBRATION_ANOMALY,
    FailureScenario.BRAKE_DEGRADATION,
]

# Vehicle types to include in training data
TRAINING_VEHICLE_TYPES: list[VehicleType] = [
    VehicleType.AMBULANCE,
    VehicleType.FIRE_TRUCK,
    VehicleType.POLICE,
]


def _make_generator_and_injector(
    vehicle_type: VehicleType,
    seed_offset: int,
) -> tuple[SimpleTelemetryGenerator, FailureInjector]:
    """Create a fresh generator/injector pair for a given vehicle type.

    Args:
        vehicle_type: The vehicle type to simulate.
        seed_offset: Added to RANDOM_SEED so each (type, scenario) pair gets
            a deterministic but distinct random stream.

    Returns:
        (generator, injector) tuple
    """
    random.seed(RANDOM_SEED + seed_offset)
    vtype_prefix = {"ambulance": "AMB", "fire_truck": "FIRE", "police": "POL"}[vehicle_type.value]
    config = AgentConfig(
        vehicle_id=f"TRN-{vtype_prefix}-{seed_offset:03d}",
        vehicle_type=vehicle_type,
        telemetry_frequency_hz=1.0,
    )
    generator = SimpleTelemetryGenerator(config)
    injector = FailureInjector(vehicle_type=vehicle_type)
    return generator, injector


def generate_synthetic_data(num_samples: int = 14000) -> pd.DataFrame:
    """Generate synthetic telemetry data with and without failures.

    Total samples are split evenly across all (vehicle_type × scenario) pairs.
    Each failure scenario begins only after a random warm-up of WARMUP_MIN–WARMUP_MAX
    normal ticks so the model learns the onset transition.

    Args:
        num_samples: Total number of feature-vector rows to produce.

    Returns:
        DataFrame with one row per extracted feature window plus a 'label' column.
    """
    scenarios_count = len(ALL_SCENARIOS)
    vehicle_types_count = len(TRAINING_VEHICLE_TYPES)
    combinations = scenarios_count * vehicle_types_count
    samples_per_combo = max(1, num_samples // combinations)

    data: list[dict] = []
    seed_offset = 0

    for vehicle_type in TRAINING_VEHICLE_TYPES:
        for scenario in ALL_SCENARIOS:
            generator, injector = _make_generator_and_injector(vehicle_type, seed_offset)
            seed_offset += 1

            extractor = FeatureExtractor(window_size=10)

            # ----------------------------------------------------------------
            # Warm-up phase: generate normal ticks before activating failure.
            # For the "normal" scenario there is no subsequent failure phase —
            # all ticks are normal so the model learns the stable baseline.
            # ----------------------------------------------------------------
            warmup_ticks = 0 if scenario is None else random.randint(WARMUP_MIN, WARMUP_MAX)

            for _ in range(warmup_ticks):
                telemetry = generator.generate(OperationalStatus.EN_ROUTE)
                extractor.add_telemetry(telemetry)
                features = extractor.extract_features()
                if features is not None:
                    row: dict[str, object] = dict(features)
                    row["label"] = "normal"
                    data.append(row)

            # ----------------------------------------------------------------
            # Main phase: activate failure (if any) and collect samples.
            # ----------------------------------------------------------------
            if scenario is not None:
                injector.activate_scenario(scenario)

            for _ in range(samples_per_combo):
                telemetry = generator.generate(OperationalStatus.EN_ROUTE)
                telemetry = injector.apply_failures(telemetry)

                extractor.add_telemetry(telemetry)
                features = extractor.extract_features()

                if features is not None:
                    row2: dict[str, object] = dict(features)
                    row2["label"] = scenario.value if scenario is not None else "normal"
                    data.append(row2)

    return pd.DataFrame(data)


def train_model(output_path: str = "src/ml/model.joblib") -> None:
    """Train the RandomForestClassifier and save it.

    Args:
        output_path: File path where the trained model will be saved.
    """
    logger.info("generating_synthetic_data")
    df = generate_synthetic_data(num_samples=14000)

    logger.info(
        "training_model", samples=len(df), label_distribution=df["label"].value_counts().to_dict()
    )

    X = df.drop(columns=["label"])
    y = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_SEED, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=15,
        random_state=RANDOM_SEED,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    report = classification_report(y_test, y_pred)
    logger.info("model_evaluation", report=f"\n{report}")

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Save model
    joblib.dump(clf, output_path)
    logger.info("model_saved", path=output_path)


if __name__ == "__main__":
    train_model()
