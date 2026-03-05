"""
Central orchestrator agent for Project AEGIS.

This module contains the OrchestratorAgent which subscribes to all vehicle
telemetry via Redis, maintains the fleet state in memory, and coordinates
emergency dispatch.
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

from src.models.alerts import PredictiveAlert
from src.models.dispatch import Dispatch, VehicleStatusSnapshot
from src.models.emergency import Emergency, EmergencyStatus
from src.models.enums import OperationalStatus, VehicleType
from src.models.telemetry import VehicleTelemetry
from src.orchestrator.dispatch_engine import DispatchEngine
from src.storage.database import db
from src.storage.repositories import AlertRepository, TelemetryRepository

logger = structlog.get_logger(__name__)

# Redis channel patterns
TELEMETRY_PATTERN = "aegis:*:telemetry:*"
ALERTS_PATTERN = "aegis:*:alerts:*"
ALERTS_CLEARED_PATTERN = "aegis:*:alerts_cleared:*"
EMERGENCY_CHANNEL = "aegis:emergencies:new"
DISPATCH_CHANNEL_PREFIX = "aegis:dispatch"

# Emergencies that stay in DISPATCHING longer than this are cancelled (no units found).
EMERGENCY_DISPATCH_TIMEOUT_MINUTES = 10
# Emergencies that stay DISPATCHED/IN_PROGRESS longer than this are auto-resolved.
EMERGENCY_MAX_DURATION_MINUTES = 30
# How often the background sweeper runs (seconds).
SWEEPER_INTERVAL_SECONDS = 30.0
# Accumulate this many telemetry records before writing them in a single DB transaction.
TELEMETRY_BATCH_SIZE = 10


class OrchestratorAgent:
    """Central brain of the AEGIS system.

    Subscribes to all vehicle channels via Redis pub/sub and maintains
    an in-memory fleet state. Processes incoming emergencies and triggers
    dispatch via the DispatchEngine.

    The fleet state is a shared mutable dict updated by telemetry messages
    and read by the DispatchEngine for unit selection.

    Attributes:
        fleet: Dict of vehicle_id -> VehicleStatusSnapshot (in-memory state).
        emergencies: Dict of emergency_id -> Emergency (in-memory).
        dispatches: Dict of emergency_id -> Dispatch (in-memory).
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

        # Optional callback for WebSocket broadcasting (injected by api.py)
        self._ws_broadcast = ws_broadcast_callback

        self.fleet: dict[str, VehicleStatusSnapshot] = {}
        self.emergencies: dict[str, Emergency] = {}
        self.dispatches: dict[str, Dispatch] = {}
        # Latest active PredictiveAlert per vehicle (cleared when alert_cleared received)
        self.active_alerts: dict[str, PredictiveAlert] = {}

        self.dispatch_engine = DispatchEngine(self.fleet)

        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self.running = False

        # Telemetry write buffer — records accumulate here until TELEMETRY_BATCH_SIZE
        # is reached, then they are flushed in a single DB transaction.
        self._telemetry_buffer: list[tuple[VehicleTelemetry, str]] = []

    async def start(self) -> None:
        """Connect to Redis and start background listener task.

        Raises:
            redis.ConnectionError: If Redis is unreachable.
        """
        self._redis = redis.Redis(
            host=self._redis_host,
            port=self._redis_port,
            password=self._redis_password,
            db=self._redis_db,
            decode_responses=True,
        )
        await self._redis.ping()

        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(
            TELEMETRY_PATTERN,
            ALERTS_PATTERN,
            ALERTS_CLEARED_PATTERN,
            EMERGENCY_CHANNEL,
        )

        self.running = True
        # Background sweeper for timed-out emergencies
        self._sweeper_task: asyncio.Task | None = asyncio.create_task(  # type: ignore[type-arg]
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
        # Flush any remaining buffered telemetry before closing
        if self._telemetry_buffer:
            await self._flush_telemetry_buffer()
        if self._pubsub:
            await self._pubsub.punsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.aclose()
        logger.info("orchestrator_stopped")

    async def run(self) -> None:
        """Main event loop - listen for Redis messages until stopped.

        Call start() before run(). This method blocks until stop() is called.
        """
        await self.start()
        try:
            async for raw in self._pubsub.listen():  # type: ignore[union-attr]
                if not self.running:
                    break
                if raw["type"] not in ("message", "pmessage"):
                    continue
                await self._handle_raw_message(raw)
        except Exception as e:
            logger.error("orchestrator_error", error=str(e), exc_info=True)
            raise
        finally:
            await self.stop()

    async def _handle_raw_message(self, raw: dict) -> None:
        """Parse and dispatch an incoming Redis pub/sub message.

        Args:
            raw: Raw message dict from redis-py pubsub listener.
        """
        channel: str = raw.get("channel", "") or raw.get("pattern", "") or ""
        data: str = raw.get("data", "")

        if not data or not isinstance(data, str):
            return

        try:
            if "telemetry" in channel:
                telemetry = VehicleTelemetry.model_validate_json(data)
                await self._handle_telemetry(telemetry)
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

        snap = self.fleet.get(vehicle_id)
        if snap is None:
            # First time seeing this vehicle - infer type from ID prefix
            vehicle_type = _infer_vehicle_type(vehicle_id)
            snap = VehicleStatusSnapshot(
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                operational_status=OperationalStatus.IDLE,
            )
            self.fleet[vehicle_id] = snap
            logger.info("new_vehicle_registered", vehicle_id=vehicle_id, type=vehicle_type.value)

            # Persist vehicle metadata
            asyncio.create_task(self._persist_vehicle(vehicle_id, vehicle_type.value, "active"))

        # Update last seen timestamp
        snap.last_seen_at = datetime.utcnow()

        # Update location
        from src.models.vehicle import Location

        try:
            snap.location = Location(
                latitude=telemetry.latitude,
                longitude=telemetry.longitude,
                timestamp=telemetry.timestamp,
            )
        except Exception:
            pass  # Location parse failure is non-fatal

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

        logger.debug("telemetry_processed", vehicle_id=vehicle_id)

        # Buffer telemetry for batched DB writes
        self._telemetry_buffer.append((telemetry, vehicle_id))
        if len(self._telemetry_buffer) >= TELEMETRY_BATCH_SIZE:
            asyncio.create_task(self._flush_telemetry_buffer())

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

    async def _flush_telemetry_buffer(self) -> None:
        """Flush the in-memory telemetry buffer to the database in one transaction.

        Drains ``self._telemetry_buffer`` atomically (swaps it for an empty list
        before the DB round-trip so concurrent callers do not double-write) and
        persists all buffered records inside a single session.
        """
        if db.engine is None:
            self._telemetry_buffer.clear()
            return

        # Swap the buffer atomically so new records keep accumulating while we write
        batch, self._telemetry_buffer = self._telemetry_buffer, []
        if not batch:
            return

        try:
            async with db.session() as session:
                repo = TelemetryRepository(session)
                for telemetry, vehicle_id in batch:
                    await repo.save_telemetry(telemetry, vehicle_id)
            logger.debug("telemetry_batch_flushed", count=len(batch))
        except Exception as e:
            logger.error("db_flush_telemetry_error", count=len(batch), error=str(e))

    async def _handle_alert(self, alert: PredictiveAlert) -> None:
        """Mark a vehicle as having an active alert and store the full alert details.

        Args:
            alert: PredictiveAlert payload from a vehicle.
        """
        vehicle_id = alert.vehicle_id
        if vehicle_id in self.fleet:
            self.fleet[vehicle_id].has_active_alert = True
        # Keep the most recent alert for API/dashboard consumption
        self.active_alerts[vehicle_id] = alert
        logger.info("alert_received", vehicle_id=vehicle_id, alert_id=alert.alert_id)

        # Persist alert in the background
        asyncio.create_task(self._persist_alert(alert, vehicle_id))

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

        if vehicle_id in self.fleet:
            self.fleet[vehicle_id].has_active_alert = False
            self.fleet[vehicle_id].operational_status = OperationalStatus.IDLE
            logger.info("alert_cleared", vehicle_id=vehicle_id)
            # Retry any emergencies waiting for units
            await self._retry_dispatching_emergencies()
        # Remove the stored alert
        self.active_alerts.pop(vehicle_id, None)

    async def _retry_dispatching_emergencies(self) -> None:
        """Attempt to dispatch emergencies that previously had no available units.

        Iterates all emergencies in DISPATCHING status and re-runs the dispatch
        engine now that a vehicle has become available.
        """
        waiting = [e for e in self.emergencies.values() if e.status == EmergencyStatus.DISPATCHING]
        for emergency in waiting:
            logger.info(
                "retrying_dispatch",
                emergency_id=emergency.emergency_id,
                emergency_type=emergency.emergency_type.value,
            )
            await self.process_emergency(emergency)

    async def _emergency_sweeper(self) -> None:
        """Background task that periodically cancels or resolves stale emergencies.

        - DISPATCHING emergencies older than EMERGENCY_DISPATCH_TIMEOUT_MINUTES
          are cancelled (no units ever became available in time).
        - DISPATCHED emergencies older than EMERGENCY_MAX_DURATION_MINUTES are
          auto-resolved (scene work is assumed complete).
        """
        while self.running:
            try:
                await asyncio.sleep(SWEEPER_INTERVAL_SECONDS)
                now = datetime.utcnow()

                for emergency in list(self.emergencies.values()):
                    age_minutes = (now - emergency.created_at).total_seconds() / 60.0

                    if emergency.status == EmergencyStatus.DISPATCHING:
                        if age_minutes >= EMERGENCY_DISPATCH_TIMEOUT_MINUTES:
                            emergency.status = EmergencyStatus.CANCELLED
                            logger.warning(
                                "emergency_cancelled_no_units",
                                emergency_id=emergency.emergency_id,
                                age_minutes=round(age_minutes, 1),
                            )

                    elif emergency.status in (
                        EmergencyStatus.DISPATCHED,
                        EmergencyStatus.IN_PROGRESS,
                    ):
                        if age_minutes >= EMERGENCY_MAX_DURATION_MINUTES:
                            try:
                                await self.resolve_emergency(emergency.emergency_id)
                                logger.info(
                                    "emergency_auto_resolved",
                                    emergency_id=emergency.emergency_id,
                                    age_minutes=round(age_minutes, 1),
                                )
                            except Exception as exc:
                                logger.error(
                                    "auto_resolve_failed",
                                    emergency_id=emergency.emergency_id,
                                    error=str(exc),
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("sweeper_error", error=str(exc))

    async def _persist_alert(self, alert: PredictiveAlert, vehicle_id: str) -> None:
        """Background task to persist alert."""
        if db.engine is None:
            return
        try:
            async with db.session() as session:
                repo = AlertRepository(session)
                await repo.save_alert(alert, vehicle_id)
        except Exception as e:
            logger.error("db_persist_alert_error", vehicle_id=vehicle_id, error=str(e))

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
        self.emergencies[emergency.emergency_id] = emergency

        dispatch = self.dispatch_engine.select_units(emergency)
        self.dispatches[emergency.emergency_id] = dispatch

        if dispatch.units:
            emergency.status = EmergencyStatus.DISPATCHED
            emergency.dispatched_at = datetime.utcnow()
        else:
            emergency.status = EmergencyStatus.DISPATCHING
            logger.warning(
                "no_units_available",
                emergency_id=emergency.emergency_id,
                emergency_type=emergency.emergency_type.value,
            )

        # Publish assignment to each vehicle
        if self._redis:
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
                    await self._redis.publish(channel, json.dumps(payload))
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
                await self._redis.publish(broadcast_channel, json.dumps(broadcast_payload))
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
        emergency = self.emergencies[emergency_id]
        emergency.status = EmergencyStatus.RESOLVED
        emergency.resolved_at = datetime.utcnow()

        released = self.dispatch_engine.release_units(emergency_id)

        # Publish resolution broadcast
        if self._redis:
            channel = f"{DISPATCH_CHANNEL_PREFIX}:{emergency_id}:resolved"
            payload = {"emergency_id": emergency_id, "released_vehicles": released}
            try:
                await self._redis.publish(channel, json.dumps(payload))
            except Exception as e:
                logger.error("resolve_broadcast_failed", emergency_id=emergency_id, error=str(e))

        logger.info(
            "emergency_resolved",
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
        total = len(self.fleet)
        available = sum(1 for s in self.fleet.values() if s.is_available)
        on_mission = sum(
            1
            for s in self.fleet.values()
            if s.operational_status.value in ("en_route", "on_scene", "returning")
        )
        vehicles_with_alerts = sum(1 for s in self.fleet.values() if s.has_active_alert)
        by_type: dict[str, dict[str, int]] = {}

        for snap in self.fleet.values():
            key = snap.vehicle_type.value
            if key not in by_type:
                by_type[key] = {"total": 0, "available": 0}
            by_type[key]["total"] += 1
            if snap.is_available:
                by_type[key]["available"] += 1

        return {
            "total_vehicles": total,
            "available_vehicles": available,
            "on_mission": on_mission,
            "vehicles_with_alerts": vehicles_with_alerts,
            "active_emergencies": sum(
                1
                for e in self.emergencies.values()
                if e.status not in (EmergencyStatus.RESOLVED, EmergencyStatus.CANCELLED)
            ),
            "by_type": by_type,
        }


def _infer_vehicle_type(vehicle_id: str) -> VehicleType:
    """Infer vehicle type from vehicle_id prefix convention.

    Args:
        vehicle_id: Vehicle identifier (e.g. AMB-001, FIRE-002, POL-003).

    Returns:
        Best-guess VehicleType, defaults to AMBULANCE if unknown.
    """
    vid = vehicle_id.upper()
    if vid.startswith("AMB"):
        return VehicleType.AMBULANCE
    if vid.startswith("FIR") or vid.startswith("FIRE"):
        return VehicleType.FIRE_TRUCK
    if vid.startswith("POL"):
        return VehicleType.POLICE
    logger.warning("unknown_vehicle_id_prefix", vehicle_id=vehicle_id)
    return VehicleType.AMBULANCE
