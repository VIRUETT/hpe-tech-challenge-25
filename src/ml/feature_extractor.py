"""
Feature extraction from sliding windows of telemetry data.

Extracts statistical features (mean, std, max/min, rate-of-change) from a
sliding window of telemetry readings.  Supports the original 3 sensor channels
plus the 3 new channels added in Track A-3 (oil_pressure_bar, vibration_ms2,
brake_pad_mm).  New channels are only included when at least one reading in the
window has a non-None value.

Feature extractor for crime prediction models.
"""

from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from src.models.telemetry import VehicleTelemetry


class TelemetryFeatureExtractor:
    """Extracts features from a sliding window of vehicle telemetry."""

    def __init__(self, window_size: int = 10) -> None:
        """
        Initialize the feature extractor.

        Args:
            window_size: Number of telemetry points to keep in the sliding window.
        """
        self.window_size = window_size
        self.history: deque[VehicleTelemetry] = deque(maxlen=window_size)

    def add_telemetry(self, telemetry: VehicleTelemetry) -> None:
        """Add a new telemetry point to the window."""
        self.history.append(telemetry)

    def extract_features(self) -> dict[str, object] | None:
        """
        Extract features from the current sliding window.

        Returns:
            Dictionary of features (values are float or str for 'label'),
            or None if the window is not yet full.
        """
        if len(self.history) < self.window_size:
            return None

        # Extract basic arrays
        engine_temps = [t.engine_temp_celsius for t in self.history]
        battery_volts = [t.battery_voltage for t in self.history]
        fuel_levels = [t.fuel_level_percent for t in self.history]
        speeds = [t.speed_kmh for t in self.history]

        features: dict[str, object] = {}

        # Engine Temperature features
        features["engine_temp_mean"] = float(np.mean(engine_temps))
        features["engine_temp_std"] = float(np.std(engine_temps))
        features["engine_temp_max"] = float(np.max(engine_temps))
        features["engine_temp_roc"] = float(engine_temps[-1] - engine_temps[0])

        # Battery Voltage features
        features["battery_voltage_mean"] = float(np.mean(battery_volts))
        features["battery_voltage_std"] = float(np.std(battery_volts))
        features["battery_voltage_min"] = float(np.min(battery_volts))
        features["battery_voltage_roc"] = float(battery_volts[-1] - battery_volts[0])

        # Fuel Level features
        features["fuel_level_mean"] = float(np.mean(fuel_levels))
        features["fuel_level_std"] = float(np.std(fuel_levels))
        features["fuel_level_roc"] = float(fuel_levels[-1] - fuel_levels[0])

        # Speed features
        features["speed_mean"] = float(np.mean(speeds))

        # ------------------------------------------------------------------
        # Extended features for new failure scenarios (Track A-3).
        # Only included when the sensor is present in the window data.
        # ------------------------------------------------------------------

        # Oil pressure (bar)
        oil_pressures = [t.oil_pressure_bar for t in self.history if t.oil_pressure_bar is not None]
        if oil_pressures:
            features["oil_pressure_mean"] = float(np.mean(oil_pressures))
            features["oil_pressure_min"] = float(np.min(oil_pressures))
            features["oil_pressure_roc"] = float(oil_pressures[-1] - oil_pressures[0])
        else:
            features["oil_pressure_mean"] = 0.0
            features["oil_pressure_min"] = 0.0
            features["oil_pressure_roc"] = 0.0

        # Vibration (m/s²)
        vibrations = [t.vibration_ms2 for t in self.history if t.vibration_ms2 is not None]
        if vibrations:
            features["vibration_mean"] = float(np.mean(vibrations))
            features["vibration_max"] = float(np.max(vibrations))
            features["vibration_roc"] = float(vibrations[-1] - vibrations[0])
        else:
            features["vibration_mean"] = 0.0
            features["vibration_max"] = 0.0
            features["vibration_roc"] = 0.0

        # Brake pad thickness (mm)
        brake_pads = [t.brake_pad_mm for t in self.history if t.brake_pad_mm is not None]
        if brake_pads:
            features["brake_pad_mean"] = float(np.mean(brake_pads))
            features["brake_pad_min"] = float(np.min(brake_pads))
            features["brake_pad_roc"] = float(brake_pads[-1] - brake_pads[0])
        else:
            features["brake_pad_mean"] = 0.0
            features["brake_pad_min"] = 0.0
            features["brake_pad_roc"] = 0.0

        return features


class CrimeFeatureExtractor:
    """Extracts and engineers features for crime prediction."""

    def __init__(self) -> None:
        """Initialize the feature extractor for crime predictions."""
        self.label_encoders: dict[str, LabelEncoder] = {}
        self.feature_columns: list[str] = []

    def engineer_training_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Process raw historical data to create features for model training.
        """
        df = df.copy()

        # Ensure date format is correct
        if "fecha_dt" in df.columns:
            # It exists but as a string, so we convert it
            df["fecha_dt"] = pd.to_datetime(df["fecha_dt"], errors="coerce")
        elif "fecha" in df.columns:
            # Fallback if only 'fecha' exists
            df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
        else:
            df["fecha_dt"] = pd.Timestamp.now()

        # Basic temporal features
        if "hour_int" not in df.columns:
            df["hour_int"] = pd.to_datetime(df["hora"], format="%H:%M", errors="coerce").dt.hour

        df["hora"] = df["hour_int"]
        df["dia_semana"] = df["fecha_dt"].dt.dayofweek
        df["mes"] = df["fecha_dt"].dt.month
        df["año"] = df["fecha_dt"].dt.year
        df["fin_semana"] = (df["dia_semana"] >= 5).astype(int)

        # Características cíclicas
        df["hora_sin"] = np.sin(2 * np.pi * df["hora"] / 24)
        df["hora_cos"] = np.cos(2 * np.pi * df["hora"] / 24)
        df["dia_sin"] = np.sin(2 * np.pi * df["dia_semana"] / 7)
        df["dia_cos"] = np.cos(2 * np.pi * df["dia_semana"] / 7)
        df["mes_sin"] = np.sin(2 * np.pi * df["mes"] / 12)
        df["mes_cos"] = np.cos(2 * np.pi * df["mes"] / 12)

        # Codificación de variables categoricas
        categorical_cols = ["crime_type", "nivel_económico", "nombre_de_la_colonia"]
        for col in categorical_cols:
            if col in df.columns:
                le = LabelEncoder()
                df[col] = df[col].fillna("desconocido")
                df[f"{col}_cod"] = le.fit_transform(df[col].astype(str))
                self.label_encoders[col] = le

        # 5. Crear variable objetivo (Target)
        if "nombre_de_la_colonia" in df.columns:
            crime_counts = df["nombre_de_la_colonia"].value_counts()
            threshold = crime_counts.quantile(0.80)
            high_risk_areas = crime_counts[crime_counts >= threshold].index.tolist()
            df["alto_riesgo"] = df["nombre_de_la_colonia"].isin(high_risk_areas).astype(int)
        else:
            df["alto_riesgo"] = 0

        # 6. Definir columnas finales a exportar
        feature_candidates = [
            "hora",
            "dia_semana",
            "mes",
            "fin_semana",
            "hora_sin",
            "hora_cos",
            "dia_sin",
            "dia_cos",
            "mes_sin",
            "mes_cos",
            "índice_densidad_poblacional",
        ]

        self.feature_columns = [feat for feat in feature_candidates if feat in df.columns]
        if "nivel_económico_cod" in df.columns:
            self.feature_columns.append("nivel_económico_cod")

        return df

    def create_time_features(self, time_point: datetime) -> dict[str, float]:
        """
        Create standard cyclical time features for real-time inference.
        """
        return {
            "hora": time_point.hour,
            "dia_semana": time_point.weekday(),
            "mes": time_point.month,
            "fin_semana": 1 if time_point.weekday() >= 5 else 0,
            "hora_sin": float(np.sin(2 * np.pi * time_point.hour / 24)),
            "hora_cos": float(np.cos(2 * np.pi * time_point.hour / 24)),
            "dia_sin": float(np.sin(2 * np.pi * time_point.weekday() / 7)),
            "dia_cos": float(np.cos(2 * np.pi * time_point.weekday() / 7)),
            "mes_sin": float(np.sin(2 * np.pi * time_point.month / 12)),
            "mes_cos": float(np.cos(2 * np.pi * time_point.month / 12)),
        }
