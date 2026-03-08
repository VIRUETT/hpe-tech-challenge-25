"""
Historical crime injector for simulation and model validation.

Synced with the AI simulation clock to inject crimes based on the
current simulated day of the week and hour. Respects SF boundaries.
"""

import random
from pathlib import Path

import pandas as pd
import structlog

from src.core.time import Clock
from src.models.emergency import (
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    Location,
    UnitsRequired,
    scale_units_by_severity,
)
from src.orchestrator.agent import OrchestratorAgent
from src.vehicle_agent.config import SF_LAT_MAX, SF_LAT_MIN, SF_LON_MAX, SF_LON_MIN

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "delitos_sf.csv"


class HistoricalCrimeInjector:
    def __init__(
        self,
        orchestrator: OrchestratorAgent,
        clock: Clock,
        csv_path: str = str(DEFAULT_CSV),
        check_interval_seconds: float = 1800.0,
        hourly_injection_probability: float = 0.25,
        max_active_historical: int = 3,
    ) -> None:
        self.orchestrator = orchestrator
        self.clock = clock
        self.csv_path = csv_path
        self.check_interval_seconds = check_interval_seconds
        self.hourly_injection_probability = hourly_injection_probability
        self.max_active_historical = max_active_historical

        self.running = False
        self.holdout_data = pd.DataFrame()
        self.last_processed_time: tuple[int, int] | None = None

    async def _dismiss_stale_historical_emergencies(self) -> None:
        """Dismiss historical emergencies older than 3 simulated hours.

        Only emergencies that are not in DISPATCHING are eligible.
        """
        now = self.clock.now()
        for emergency in list(self.orchestrator.emergencies.values()):
            if emergency.reported_by != "historical_playback":
                continue
            if emergency.status in (
                EmergencyStatus.DISPATCHED,
                EmergencyStatus.IN_PROGRESS,
                EmergencyStatus.RESOLVED,
                EmergencyStatus.CANCELLED,
                EmergencyStatus.DISMISSED,
            ):
                continue

            age_hours = (now - emergency.created_at).total_seconds() / 3600.0
            if age_hours < 5.0:
                continue

            try:
                await self.orchestrator.dismiss_emergency(emergency.emergency_id)
                logger.info(
                    "historical_emergency_auto_dismissed",
                    emergency_id=emergency.emergency_id,
                    age_hours=round(age_hours, 2),
                )
            except Exception as e:
                logger.warning(
                    "historical_dismiss_failed",
                    emergency_id=emergency.emergency_id,
                    error=str(e),
                )

    def _active_historical_emergencies(self) -> int:
        return sum(
            1
            for emergency in self.orchestrator.emergencies.values()
            if emergency.reported_by == "historical_playback"
            and emergency.status
            not in (
                EmergencyStatus.RESOLVED,
                EmergencyStatus.CANCELLED,
                EmergencyStatus.DISMISSED,
            )
        )

    def _units_for_crime_type(self, crime_type: str) -> UnitsRequired:
        """Return vehicle requirements for a historical crime subtype."""
        normalized = crime_type.strip().lower()

        if any(token in normalized for token in ("tiroteo", "homicidio", "arma")):
            return UnitsRequired(ambulances=1, police=2)
        if any(token in normalized for token in ("incendio", "explosion")):
            return UnitsRequired(ambulances=1, fire_trucks=1, police=1)
        if any(token in normalized for token in ("vial", "accidente", "choque", "atropello")):
            return UnitsRequired(ambulances=1, police=1)
        if any(token in normalized for token in ("violencia", "agresion", "secuestro")):
            return UnitsRequired(ambulances=1, police=2)
        if any(token in normalized for token in ("robo", "asalto", "hurto", "allanamiento")):
            return UnitsRequired(police=1)

        return UnitsRequired(police=1)

    def _prepare_data(self) -> None:
        try:
            df = pd.read_csv(self.csv_path)
            if "fecha_dt" in df.columns:
                df["fecha_dt"] = pd.to_datetime(df["fecha_dt"], errors="coerce")
            elif "fecha" in df.columns:
                df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
            if "hour_int" not in df.columns:
                df["hour_int"] = pd.to_datetime(df["hora"], format="%H:%M", errors="coerce").dt.hour

            df["day_of_week"] = df["fecha_dt"].dt.dayofweek
            df = df.sort_values(by=["fecha_dt", "hora"])
            split_idx = int(len(df) * 0.8)
            self.holdout_data = df.iloc[split_idx:].copy()
            logger.info("historical_data_prepared", total_playback_events=len(self.holdout_data))
        except Exception as e:
            logger.error("failed_to_load_historical_data", error=str(e))

    async def start(self) -> None:
        self._prepare_data()
        if self.holdout_data.empty:
            return

        self.running = True
        logger.info("historical_injector_started", start_sim_time=self.clock.now().isoformat())

        while self.running:
            current_time = self.clock.now()
            current_dow = current_time.weekday()
            current_hour = current_time.hour

            await self._dismiss_stale_historical_emergencies()

            if (current_dow, current_hour) != self.last_processed_time:
                self.last_processed_time = (current_dow, current_hour)

                if self._active_historical_emergencies() >= self.max_active_historical:
                    await self.clock.sleep(self.check_interval_seconds)
                    continue

                if random.random() > self.hourly_injection_probability:
                    await self.clock.sleep(self.check_interval_seconds)
                    continue

                matching_crimes = self.holdout_data[
                    (self.holdout_data["day_of_week"] == current_dow)
                    & (self.holdout_data["hour_int"] == current_hour)
                ]

                if not matching_crimes.empty:
                    sampled_crimes = matching_crimes.sample(n=1)
                    for _, row in sampled_crimes.iterrows():
                        try:
                            await self._inject_crime(row)
                        except Exception as e:
                            logger.error("historical_injection_error", error=str(e), exc_info=True)

            await self.clock.sleep(self.check_interval_seconds)

    def stop(self) -> None:
        self.running = False

    async def _inject_crime(self, row: pd.Series) -> None:
        neighborhood = row.get("nombre_de_la_colonia", "Unknown Area")
        crime_type_str = row.get("crime_type", "crime").upper()
        # Historical playback defaults to moderate severity so one police unit
        # is usually enough and dispatch remains feasible with small fleets.
        severity = EmergencySeverity.MODERATE

        lat = max(SF_LAT_MIN, min(SF_LAT_MAX, float(row["latitud"])))
        lon = max(SF_LON_MIN, min(SF_LON_MAX, float(row["longitud"])))

        location = Location(latitude=lat, longitude=lon, timestamp=self.clock.now())
        em_type = EmergencyType.CRIME
        base_units = self._units_for_crime_type(crime_type_str)
        units_required = scale_units_by_severity(base_units, severity)
        sim_time_str = self.clock.now().strftime("%A %H:%M")

        emergency = Emergency(
            emergency_type=em_type,
            severity=severity,
            location=location,
            address=neighborhood,
            description=f"ACTUAL CRIME [{sim_time_str}]: {crime_type_str} reported historically",
            units_required=units_required,
            reported_by="historical_playback",
            created_at=self.clock.now(),
        )
        await self.orchestrator.process_emergency(emergency)
