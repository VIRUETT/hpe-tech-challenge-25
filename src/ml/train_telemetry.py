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

from src.ml.feature_extractor import TelemetryFeatureExtractor
from src.models.enums import FailureScenario, OperationalStatus, VehicleType
from src.vehicle_agent.config import AgentConfig
from src.vehicle_agent.failure_injector import FailureInjector
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

logger = structlog.get_logger(__name__)


class SyntheticDataGenerator:
    """Handles the generation of synthetic telemetry data for vehicle training."""

    def __init__(self, random_seed: int = 42) -> None:
        self.random_seed = random_seed
        self.warmup_min = 200
        self.warmup_max = 500
        self.training_vehicle_types = [
            VehicleType.AMBULANCE,
            VehicleType.FIRE_TRUCK,
            VehicleType.POLICE,
        ]
        self.all_scenarios = [
            None,  # Normal — no failure
            FailureScenario.ENGINE_OVERHEAT,
            FailureScenario.BATTERY_DEGRADATION,
            FailureScenario.FUEL_LEAK,
            FailureScenario.OIL_PRESSURE_DROP,
            FailureScenario.VIBRATION_ANOMALY,
            FailureScenario.BRAKE_DEGRADATION,
        ]

    def _make_generator_and_injector(
        self, vehicle_type: VehicleType, seed_offset: int
    ) -> tuple[SimpleTelemetryGenerator, FailureInjector]:
        """Create a fresh generator/injector pair for a given vehicle type.

        Args:
            vehicle_type: The vehicle type to simulate.
            seed_offset: Added to RANDOM_SEED so each (type, scenario) pair gets
                a deterministic but distinct random stream.

        Returns:
            (generator, injector) tuple
        """
        random.seed(self.random_seed + seed_offset)
        vtype_prefix = {"ambulance": "AMB", "fire_truck": "FIRE", "police": "POL"}[
            vehicle_type.value
        ]

        config = AgentConfig(
            vehicle_id=f"TRN-{vtype_prefix}-{seed_offset:03d}",
            vehicle_type=vehicle_type,
            telemetry_frequency_hz=1.0,
        )
        generator = SimpleTelemetryGenerator(config)
        injector = FailureInjector(vehicle_type=vehicle_type)

        return generator, injector

    def generate(self, num_samples: int = 14000) -> pd.DataFrame:
        """Generate synthetic telemetry data with and without failures.

        Total samples are split evenly across all (vehicle_type × scenario) pairs.
        Each failure scenario begins only after a random warm-up of WARMUP_MIN–WARMUP_MAX
        normal ticks so the model learns the onset transition.

        Args:
            num_samples: Total number of feature-vector rows to produce.

        Returns:
            DataFrame with one row per extracted feature window plus a 'label' column.
        """
        combinations = len(self.all_scenarios) * len(self.training_vehicle_types)
        samples_per_combo = max(1, num_samples // combinations)

        data: list[dict] = []
        seed_offset = 0

        for vehicle_type in self.training_vehicle_types:
            for scenario in self.all_scenarios:
                generator, injector = self._make_generator_and_injector(vehicle_type, seed_offset)
                seed_offset += 1
                extractor = TelemetryFeatureExtractor(window_size=10)

                # Warm-up phase
                warmup_ticks = (
                    0 if scenario is None else random.randint(self.warmup_min, self.warmup_max)
                )
                for _ in range(warmup_ticks):
                    telemetry = generator.generate(OperationalStatus.EN_ROUTE)
                    extractor.add_telemetry(telemetry)
                    features = extractor.extract_features()
                    if features is not None:
                        row = dict(features)
                        row["label"] = "normal"
                        data.append(row)

                # Main phase (Failure activation)
                if scenario is not None:
                    injector.activate_scenario(scenario)

                for _ in range(samples_per_combo):
                    telemetry = generator.generate(OperationalStatus.EN_ROUTE)
                    telemetry = injector.apply_failures(telemetry)
                    extractor.add_telemetry(telemetry)
                    features = extractor.extract_features()

                    if features is not None:
                        row2 = dict(features)
                        row2["label"] = scenario.value if scenario is not None else "normal"
                        data.append(row2)

        return pd.DataFrame(data)


class TelemetryModelTrainer:
    """Handles the training, evaluation, and exporting of the anomaly detection model."""

    def __init__(self, random_seed: int = 42) -> None:
        self.random_seed = random_seed

    def train_and_save(
        self, output_path: str = "src/ml/telemetry_model.joblib", num_samples: int = 14000
    ) -> None:
        """Train the RandomForestClassifier and save it.

        Args:
            output_path: File path where the trained model will be saved.
        """
        logger.info("generating_synthetic_data")
        data_generator = SyntheticDataGenerator(random_seed=self.random_seed)
        df = data_generator.generate(num_samples=num_samples)

        logger.info(
            "training_model",
            samples=len(df),
            label_distribution=df["label"].value_counts().to_dict(),
        )

        X = df.drop(columns=["label"])
        y = df["label"]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_seed, stratify=y
        )

        clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            random_state=self.random_seed,
            class_weight="balanced",
        )

        clf.fit(X_train, y_train)

        # Evaluate
        y_pred = clf.predict(X_test)
        report = classification_report(y_test, y_pred)
        logger.info("model_evaluation", report=f"\n{report}")

        # Ensure directory exists and save model
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        joblib.dump(clf, output_path)
        logger.info("model_saved", path=output_path)


if __name__ == "__main__":
    trainer = TelemetryModelTrainer()
    trainer.train_and_save()
