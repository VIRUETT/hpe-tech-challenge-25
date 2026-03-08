"""
Offline training script for the crime prediction model.
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.ml.feature_extractor import CrimeFeatureExtractor


def train_crime_model(csv_path: str, output_model_path: str = "src/ml/crime_model.joblib"):
    """
    Loads historical crime data, extracts features, trains a Random Forest model,
    and exports the model artifacts for real-time dispatching.
    """
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return

    extractor = CrimeFeatureExtractor()
    df_processed = extractor.engineer_training_features(df)

    # Calculate neighborhood statistics and GPS CENTROIDS (Crucial for AEGIS Dispatch Engine)
    neighborhood_stats = {}

    # We use the original Spanish column names here to match the CSV headers
    if "nombre_de_la_colonia" in df_processed.columns:
        for neighborhood in df_processed["nombre_de_la_colonia"].unique():
            neighborhood_data = df_processed[df_processed["nombre_de_la_colonia"] == neighborhood]

            # Average coordinates (Centroid) to send patrols to
            avg_latitude = neighborhood_data["latitud"].mean()
            avg_longitude = neighborhood_data["longitud"].mean()

            # Most common crime type and peak hours
            crime_types = (
                neighborhood_data["crime_type"].value_counts().head(3).to_dict()
                if "crime_type" in neighborhood_data.columns
                else {}
            )
            peak_hours = (
                neighborhood_data["hour_int"].value_counts().head(3).index.tolist()
                if "hour_int" in neighborhood_data.columns
                else []
            )
            avg_density = (
                neighborhood_data["índice_densidad_poblacional"].mean()
                if "índice_densidad_poblacional" in neighborhood_data.columns
                else 0
            )

            # Most common economic level
            economic_level = (
                neighborhood_data["nivel_económico"].mode()[0]
                if ("nivel_económico" in neighborhood_data.columns and len(neighborhood_data) > 0)
                else "unknown"
            )

            neighborhood_stats[neighborhood] = {
                "centroid_lat": avg_latitude,
                "centroid_lon": avg_longitude,
                "crime_types": crime_types,
                "peak_hours": peak_hours,
                "avg_density": avg_density,
                "economic_level": economic_level,
            }

    # Prepare data for the ML model
    feature_columns = extractor.feature_columns

    # Filter out null data based on the extracted target variable ('alto_riesgo')
    required_cols = feature_columns + ["alto_riesgo"]
    available_cols = [col for col in required_cols if col in df_processed.columns]
    df_model = df_processed[available_cols].dropna()

    X = df_model[feature_columns]
    y = df_model["alto_riesgo"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Scale the features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train the Random Forest Classifier
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=20,
        min_samples_split=5,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    rf_model.fit(X_train_scaled, y_train)

    # Evaluate the model
    y_pred = rf_model.predict(X_test_scaled)
    acc = accuracy_score(y_test, y_pred)

    # Save the complete package to disk
    model_package = {
        "model": rf_model,
        "scaler": scaler,
        "extractor": extractor,
        "neighborhood_stats": neighborhood_stats,
    }
    joblib.dump(model_package, output_model_path)


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    csv_file = PROJECT_ROOT / "data" / "delitos_sf.csv"
    # Execute the training pipeline
    train_crime_model(str(csv_file))
