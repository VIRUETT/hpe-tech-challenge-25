"""
Central orchestrator agent for Project AEGIS.

This module contains the OrchestratorAgent which subscribes to all vehicle
telemetry via Redis, maintains the fleet state in memory, and coordinates
emergency dispatch.
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from src.core.messaging import BusMessage, MessageBus
from src.core.persistence import AlertSink, TelemetrySink
from src.core.time import Clock, RealClock
from src.infrastructure.redis_bus import RedisMessageBus
from src.models.alerts import CrimePrediction, PredictiveAlert
from src.models.dispatch import Dispatch
from src.models.emergency import Emergency, EmergencyStatus
from src.models.enums import OperationalStatus
from src.models.events import VehicleRegistrationEvent
from src.models.telemetry import VehicleTelemetry
from src.orchestrator.emergency_service import EmergencyService
from src.orchestrator.fleet_service import FleetService
from src.orchestrator.persistence import DatabaseAlertPersister, DatabaseTelemetryPersister
from src.storage.database import db
from src.storage.repositories import TelemetryRepository

logger = structlog.get_logger(__name__)

# Redis channel patterns
TELEMETRY_PATTERN = "aegis:*:telemetry:*"
ALERTS_PATTERN = "aegis:*:alerts:*"
ALERTS_CLEARED_PATTERN = "aegis:*:alerts_cleared:*"
EMERGENCY_CHANNEL = "aegis:emergencies:new"
VEHICLE_REGISTER_PATTERN = "aegis:*:vehicles:register"
DISPATCH_CHANNEL_PREFIX = "aegis:dispatch"

# How often the background sweeper runs (seconds).
SWEEPER_INTERVAL_SECONDS = 30.0


class OrchestratorAgent:
    """Central brain of the AEGIS system.

    Subscribes to all vehicle channels via Redis pub/sub, handles background
    database persistence, and broadcasts real-time WebSocket updates.

    Delegates all core domain logic to dedicated services:
    - FleetService: Manages vehicle telemetry, status updates, and alerts.
    - EmergencyService: Manages incoming emergencies, unit selection (via
      DispatchEngine), and timeout rules.

    Attributes:
        fleet_service: Domain service managing the fleet state.
        emergency_service: Domain service managing emergency routing and dispatch.
        fleet: Aliased dict of vehicle_id -> VehicleStatusSnapshot (managed by FleetService).
        emergencies: Aliased dict of emergency_id -> Emergency (managed by EmergencyService).
        dispatches: Aliased dict of emergency_id -> Dispatch (managed by EmergencyService).
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_password: str | None = None,
        redis_db: int = 0,
        fleet_id: str = "fleet01",
        ws_broadcast_callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
        | None = None,
        message_bus: MessageBus | None = None,
        clock: Clock | None = None,
        telemetry_sink: TelemetrySink | None = None,
        alert_sink: AlertSink | None = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            redis_host: Redis server hostname.
            redis_port: Redis server port.
            redis_password: Optional Redis password.
            redis_db: Redis database number.
            fleet_id: Fleet identifier for channel naming.
            ws_broadcast_callback: Optional async callable ``(event_type, data)``
                used to push real-time events to WebSocket clients.  When
                provided it is called on every processed telemetry tick
                (``telemetry.update``) and on emergency state changes.
        """
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_password = redis_password
        self._redis_db = redis_db
        self._fleet_id = fleet_id
        self._clock = clock or RealClock()

        # Optional callback for WebSocket broadcasting (injected by api.py)
        self._ws_broadcast = ws_broadcast_callback

        self.fleet_service = FleetService()
        self.fleet = self.fleet_service.fleet

        self.emergency_service = EmergencyService(self.fleet)

        self.emergencies = self.emergency_service.emergencies
        self.dispatches = self.emergency_service.dispatches
        self.active_alerts = self.fleet_service.active_alerts
        self.active_crime_predictions: dict[str, CrimePrediction] = {}

        self._bus = message_bus or RedisMessageBus(
            host=self._redis_host,
            port=self._redis_port,
            password=self._redis_password,
            db=self._redis_db,
        )

        self._telemetry_sink = telemetry_sink or DatabaseTelemetryPersister(batch_size=10)
        self._alert_sink = alert_sink or DatabaseAlertPersister()
        self.running = False

    async def start(self) -> None:
        """Connect to Redis and start background listener task.

        Raises:
            RuntimeError: If messaging backend is unreachable.
        """
        await self._bus.connect()

        self.running = True
        # Background sweeper for timed-out emergencies
        self._sweeper_task: asyncio.Task[Any] | None = asyncio.create_task(
            self._emergency_sweeper(), name="emergency-sweeper"
        )
        logger.info(
            "orchestrator_started",
            redis_host=self._redis_host,
            fleet_id=self._fleet_id,
        )

    async def stop(self) -> None:
        """Gracefully stop the orchestrator and close Redis connection."""
        self.running = False
        if hasattr(self, "_sweeper_task") and self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
        await self._telemetry_sink.close()
        await self._bus.close()
        logger.info("orchestrator_stopped")

    async def run(self) -> None:
        """Main event loop - listen for Redis messages until stopped.

        Call start() before run(). This method blocks until stop() is called.
        """
        await self.start()
        try:
            async for message in self._bus.subscribe_patterns(
                TELEMETRY_PATTERN,
                ALERTS_PATTERN,
                ALERTS_CLEARED_PATTERN,
                EMERGENCY_CHANNEL,
                VEHICLE_REGISTER_PATTERN,
            ):
                if not self.running:
                    break
                await self._handle_raw_message(message)
        except Exception as e:
            logger.error("orchestrator_error", error=str(e), exc_info=True)
            raise
        finally:
            await self.stop()

    async def _handle_raw_message(self, raw: BusMessage | dict[str, Any]) -> None:
        """Parse and dispatch an incoming Redis pub/sub message.

        Args:
            raw: Raw message dict from redis-py pubsub listener.
        """
        if isinstance(raw, BusMessage):
            channel = raw.channel
            data = raw.data
        else:
            channel = raw.get("channel", "") or raw.get("pattern", "") or ""
            data = raw.get("data", "")

        if not data or not isinstance(data, str):
            return

        try:
            if "telemetry" in channel:
                telemetry = VehicleTelemetry.model_validate_json(data)
                await self._handle_telemetry(telemetry)
            elif "vehicles:register" in channel:
                registration = VehicleRegistrationEvent.model_validate_json(data)
                await self._handle_vehicle_registration(registration)
            elif "alerts_cleared" in channel:
                await self._handle_alert_cleared(data)
            elif "alerts" in channel:
                alert = PredictiveAlert.model_validate_json(data)
                await self._handle_alert(alert)
            else:
                logger.debug("unhandled_channel", channel=channel)
        except Exception as e:
            logger.warning("message_parse_error", channel=channel, error=str(e))
            return

    async def _handle_telemetry(self, telemetry: VehicleTelemetry) -> None:
        """Update fleet state from a telemetry message.

        Args:
            telemetry: VehicleTelemetry payload from a vehicle.
        """
        vehicle_id = telemetry.vehicle_id

        is_new, vehicle_type, snap = self.fleet_service.process_telemetry(telemetry)

        if is_new and vehicle_type:
            logger.info("new_vehicle_registered", vehicle_id=vehicle_id, type=vehicle_type.value)
            # Persist vehicle metadata
            asyncio.create_task(self._persist_vehicle(vehicle_id, vehicle_type.value, "active"))

        # Update key health metrics
        snap.battery_voltage = float(telemetry.battery_voltage)
        snap.fuel_level_percent = float(telemetry.fuel_level_percent)
        snap.engine_temp_celsius = float(telemetry.engine_temp_celsius)
        snap.oil_pressure_bar = (
            float(telemetry.oil_pressure_bar) if telemetry.oil_pressure_bar is not None else None
        )
        snap.vibration_ms2 = (
            float(telemetry.vibration_ms2) if telemetry.vibration_ms2 is not None else None
        )
        snap.brake_pad_mm = (
            float(telemetry.brake_pad_mm) if telemetry.brake_pad_mm is not None else None
        )

        # Update status from vehicle when provided (e.g. ON_SCENE on arrival)
        if telemetry.operational_status is not None:
            try:
                snap.operational_status = OperationalStatus(telemetry.operational_status)
            except ValueError:
                pass  # Ignore unknown status strings

        logger.debug("telemetry_processed", vehicle_id=vehicle_id)

        # Enqueue telemetry for asynchronous persistence
        asyncio.create_task(self._telemetry_sink.enqueue(telemetry, vehicle_id))

        # Broadcast live snapshot to WebSocket clients if a callback is registered
        if self._ws_broadcast is not None:
            asyncio.create_task(
                self._ws_broadcast(
                    "telemetry.update",
                    {
                        "vehicle_id": vehicle_id,
                        "latitude": telemetry.latitude,
                        "longitude": telemetry.longitude,
                        "engine_temp_celsius": float(telemetry.engine_temp_celsius),
                        "battery_voltage": float(telemetry.battery_voltage),
                        "fuel_level_percent": float(telemetry.fuel_level_percent),
                        "oil_pressure_bar": float(telemetry.oil_pressure_bar)
                        if telemetry.oil_pressure_bar is not None
                        else None,
                        "vibration_ms2": float(telemetry.vibration_ms2)
                        if telemetry.vibration_ms2 is not None
                        else None,
                        "brake_pad_mm": float(telemetry.brake_pad_mm)
                        if telemetry.brake_pad_mm is not None
                        else None,
                        "operational_status": snap.operational_status.value,
                        "timestamp": telemetry.timestamp.isoformat(),
                    },
                )
            )

    async def _handle_vehicle_registration(self, event: VehicleRegistrationEvent) -> None:
        """Register vehicle metadata from explicit agent registration events."""
        payload = event.payload
        is_new, _snapshot = self.fleet_service.register_vehicle(
            payload.vehicle_id,
            payload.vehicle_type,
            payload.operational_status,
        )
        if is_new:
            logger.info(
                "vehicle_registration_received",
                vehicle_id=payload.vehicle_id,
                vehicle_type=payload.vehicle_type.value,
            )
        if db.engine is not None:
            asyncio.create_task(
                self._persist_vehicle(payload.vehicle_id, payload.vehicle_type.value, "active")
            )

    async def _persist_vehicle(self, vehicle_id: str, vehicle_type: str, status: str) -> None:
        """Background task to persist vehicle metadata."""
        if db.engine is None:
            return
        try:
            async with db.session() as session:
                repo = TelemetryRepository(session)
                await repo.upsert_vehicle(vehicle_id, vehicle_type, status)
        except Exception as e:
            logger.error("db_persist_vehicle_error", vehicle_id=vehicle_id, error=str(e))

    async def _handle_alert(self, alert: PredictiveAlert) -> None:
        """Mark a vehicle as having an active alert and store the full alert details.

        Args:
            alert: PredictiveAlert payload from a vehicle.
        """
        vehicle_id = alert.vehicle_id

        self.fleet_service.handle_alert(alert)
        logger.info("alert_received", vehicle_id=vehicle_id, alert_id=alert.alert_id)

        # Persist alert in the background
        asyncio.create_task(self._alert_sink.persist_alert(alert, vehicle_id))

    async def _handle_alert_cleared(self, raw_data: str) -> None:
        """Clear the active-alert flag for a vehicle that completed repairs.

        When a vehicle publishes an ``alerts_cleared`` message after its repair
        cycle, the orchestrator resets ``has_active_alert`` so the vehicle is
        eligible for dispatch again. It also triggers a retry of any emergencies
        that are still waiting for units.

        Args:
            raw_data: JSON string with at least ``{"vehicle_id": "..."}``
        """
        try:
            payload = json.loads(raw_data)
            vehicle_id = payload.get("vehicle_id", "")
        except (json.JSONDecodeError, AttributeError):
            logger.warning("alert_cleared_parse_error", raw=raw_data)
            return

        self.fleet_service.clear_alert(vehicle_id)
        logger.info("alert_cleared", vehicle_id=vehicle_id)

        await self._retry_dispatching_emergencies()

    async def _retry_dispatching_emergencies(self) -> None:
        """Attempt to dispatch emergencies that previously had no available units.

        Iterates all emergencies in DISPATCHING status and re-runs the dispatch
        engine now that a vehicle has become available.
        """
        waiting = self.emergency_service.get_dispatching_emergencies()
        for emergency in waiting:
            logger.info(
                "retrying_dispatch",
                emergency_id=emergency.emergency_id,
                emergency_type=emergency.emergency_type.value,
            )
            await self.process_emergency(emergency)

    async def _emergency_sweeper(self) -> None:
        """Background task that periodically cancels or dismisses stale emergencies.

        - DISPATCHING emergencies older than EMERGENCY_DISPATCH_TIMEOUT_MINUTES
          are cancelled (no units ever became available in time).
        - DISPATCHED/IN_PROGRESS emergencies older than
          EMERGENCY_MAX_DURATION_MINUTES are auto-dismissed.
        """
        while self.running:
            try:
                await self._clock.sleep(SWEEPER_INTERVAL_SECONDS)

                to_cancel, to_dismiss = self.emergency_service.evaluate_stale_emergencies()

                for emergency in to_cancel:
                    logger.warning(
                        "emergency_cancelled_no_units",
                        emergency_id=emergency.emergency_id,
                    )

                for emergency in to_dismiss:
                    try:
                        await self.dismiss_emergency(emergency.emergency_id)
                        logger.info(
                            "emergency_auto_dismissed",
                            emergency_id=emergency.emergency_id,
                        )
                    except Exception as exc:
                        logger.error(
                            "auto_dismiss_failed",
                            emergency_id=emergency.emergency_id,
                            error=str(exc),
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("sweeper_error", error=str(exc))

    async def process_emergency(self, emergency: Emergency) -> Dispatch:
        """Process a new emergency: run dispatch and publish assignments to Redis.

        This is the core coordination method. It:
        1. Stores the emergency.
        2. Runs the DispatchEngine to select nearest available units.
        3. Updates the emergency status.
        4. Publishes assignment messages to each dispatched vehicle.
        5. Publishes a broadcast so all agents know the emergency is taken.

        Args:
            emergency: The newly registered Emergency.

        Returns:
            The resulting Dispatch record.
        """
        # Delegate to domain service
        dispatch = self.emergency_service.process_emergency(emergency)

        if not dispatch.units:
            logger.warning(
                "no_units_available",
                emergency_id=emergency.emergency_id,
                emergency_type=emergency.emergency_type.value,
            )

        # Publish assignment to each vehicle
        if self.running:
            for unit in dispatch.units:
                channel = f"aegis:{self._fleet_id}:commands:{unit.vehicle_id}"
                payload = {
                    "command": "dispatch",
                    "emergency_id": emergency.emergency_id,
                    "emergency_type": emergency.emergency_type.value,
                    "location": emergency.location.model_dump(mode="json"),
                    "dispatch_id": dispatch.dispatch_id,
                }
                try:
                    await self._bus.publish(channel, json.dumps(payload))
                except Exception as e:
                    logger.error(
                        "dispatch_publish_failed",
                        vehicle_id=unit.vehicle_id,
                        error=str(e),
                    )

            # Broadcast to all: this emergency has been taken
            broadcast_channel = f"{DISPATCH_CHANNEL_PREFIX}:{emergency.emergency_id}:assigned"
            broadcast_payload = {
                "emergency_id": emergency.emergency_id,
                "dispatch_id": dispatch.dispatch_id,
                "assigned_vehicles": dispatch.vehicle_ids,
            }
            try:
                await self._bus.publish(broadcast_channel, json.dumps(broadcast_payload))
            except Exception as e:
                logger.error("broadcast_failed", emergency_id=emergency.emergency_id, error=str(e))

        logger.info(
            "emergency_processed",
            emergency_id=emergency.emergency_id,
            status=emergency.status.value,
            units_dispatched=len(dispatch.units),
            vehicle_ids=dispatch.vehicle_ids,
        )

        return dispatch

    async def resolve_emergency(self, emergency_id: str) -> list[str]:
        """Mark an emergency as resolved and release its units back to IDLE.

        Args:
            emergency_id: The ID of the emergency to resolve.

        Returns:
            List of vehicle_ids that were released.

        Raises:
            KeyError: If the emergency_id is not found.
        """
        released = self.emergency_service.resolve_emergency(emergency_id)

        # Publish resolution broadcast
        if self.running:
            channel = f"{DISPATCH_CHANNEL_PREFIX}:{emergency_id}:resolved"
            payload = {
                "command": "resolve",
                "emergency_id": emergency_id,
                "released_vehicles": released,
            }
            try:
                await self._bus.publish(channel, json.dumps(payload))
            except Exception as e:
                logger.error("resolve_broadcast_failed", emergency_id=emergency_id, error=str(e))

        logger.info(
            "emergency_resolved",
            emergency_id=emergency_id,
            released_vehicles=released,
        )
        return released

    async def process_crime_prediction(self, prediction: CrimePrediction) -> None:
        """Store and broadcast an AI crime prediction (non-dispatching event)."""
        self.active_crime_predictions[prediction.prediction_id] = prediction

        logger.info(
            "crime_prediction_processed",
            prediction_id=prediction.prediction_id,
            neighborhood=prediction.neighborhood,
            risk_probability=prediction.risk_probability,
            severity=prediction.severity.value,
        )

        if self._ws_broadcast is not None:
            asyncio.create_task(
                self._ws_broadcast(
                    "prediction.created",
                    {
                        "prediction_id": prediction.prediction_id,
                        "neighborhood": prediction.neighborhood,
                        "timestamp": prediction.timestamp.isoformat(),
                        "risk_probability": prediction.risk_probability,
                        "confidence": prediction.confidence,
                        "severity": prediction.severity.value,
                        "latitude": prediction.latitude,
                        "longitude": prediction.longitude,
                        "predicted_crime_type": prediction.predicted_crime_type,
                        "description": prediction.description,
                        "source": prediction.source,
                    },
                )
            )

    async def resolve_crime_prediction(self, prediction_id: str) -> None:
        """Resolve and remove an existing AI crime prediction."""
        prediction = self.active_crime_predictions.pop(prediction_id, None)
        if prediction is None:
            logger.warning("crime_prediction_not_found", prediction_id=prediction_id)
            return

        logger.info(
            "crime_prediction_resolved",
            prediction_id=prediction_id,
            neighborhood=prediction.neighborhood,
        )

        if self._ws_broadcast is not None:
            asyncio.create_task(
                self._ws_broadcast(
                    "prediction.resolved",
                    {
                        "prediction_id": prediction.prediction_id,
                        "neighborhood": prediction.neighborhood,
                        "timestamp": self._clock.now().isoformat(),
                        "source": prediction.source,
                    },
                )
            )
    async def dismiss_emergency(self, emergency_id: str) -> list[str]:
        """Mark an emergency as dismissed and release assigned units."""
        released = self.emergency_service.dismiss_emergency(emergency_id)

        if self.running:
            channel = f"{DISPATCH_CHANNEL_PREFIX}:{emergency_id}:dismissed"
            payload = {
                "command": "dismiss",
                "emergency_id": emergency_id,
                "released_vehicles": released,
            }
            try:
                await self._bus.publish(channel, json.dumps(payload))
            except Exception as e:
                logger.error("dismiss_broadcast_failed", emergency_id=emergency_id, error=str(e))

        logger.info(
            "emergency_dismissed",
            emergency_id=emergency_id,
            released_vehicles=released,
        )
        return released

    def get_fleet_summary(self) -> dict:
        """Return a summary of the current fleet state.

        Returns:
            Dict with total count, available count, on-mission count,
            vehicles with alerts, active emergencies, and per-type breakdown.
        """
        active_emergencies_count = sum(
            1
            for e in self.emergencies.values()
            if e.status
            not in (
                EmergencyStatus.RESOLVED,
                EmergencyStatus.CANCELLED,
                EmergencyStatus.DISMISSED,
            )
        )
        return self.fleet_service.get_summary(active_emergencies_count)
