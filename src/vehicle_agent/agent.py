"""
Main vehicle agent orchestrator.

This module contains the VehicleAgent class which coordinates all subsystems
and manages the main event loop.
"""

import asyncio
import json
import signal
from datetime import UTC, datetime
from typing import Any

import structlog

from src.ml.predictor import Predictor
from src.models.enums import OperationalStatus
from src.vehicle_agent.anomaly_detector import AnomalyDetector
from src.vehicle_agent.config import AgentConfig
from src.vehicle_agent.failure_injector import FailureInjector
from src.vehicle_agent.failure_scheduler import FailureScheduler
from src.vehicle_agent.redis_client import RedisClient
from src.vehicle_agent.telemetry_generator import SimpleTelemetryGenerator

# How long (seconds) the vehicle stays in MAINTENANCE before returning to IDLE.
# Failures resolve slowly: 3 minutes average, ±1 minute jitter applied at runtime.
REPAIR_DURATION_SECONDS = 180.0

logger = structlog.get_logger(__name__)


class VehicleAgent:
    """Main vehicle agent orchestrator.

    Coordinates telemetry generation, Redis communication, and manages the
    agent lifecycle (start, run, stop).

    The agent runs a main loop at the configured frequency (default 1 Hz),
    generating and publishing telemetry data to Redis.

    It also subscribes to its own commands channel so the orchestrator can
    dispatch it to an emergency.  On receiving a ``dispatch`` command the
    agent transitions to EN_ROUTE.  On receiving a ``resolve`` broadcast it
    returns to IDLE.

    Attributes:
        operational_status: Current operational status of the vehicle.
        current_emergency_id: ID of the emergency the vehicle is handling, if any.
    """

    def __init__(self, config: AgentConfig) -> None:
        """
        Initialize vehicle agent.

        Args:
            config: Agent configuration
        """
        self.config = config
        self.running = False
        self.uptime_seconds = 0.0
        self.heartbeat_counter = 0

        # Mutable operational state (updated by dispatch commands)
        self.operational_status: OperationalStatus = config.initial_status
        self.current_emergency_id: str | None = None

        # Repair state: set when the vehicle enters MAINTENANCE
        self._repair_started_at: datetime | None = None
        self._repair_duration_seconds: float = 0.0

        # Internal task handle for the command listener
        self._command_listener_task: asyncio.Task | None = None  # type: ignore[type-arg]

        # Initialize components
        self.redis_client = RedisClient(config)
        self.telemetry_generator = SimpleTelemetryGenerator(config)
        self.failure_injector = FailureInjector(vehicle_type=config.vehicle_type)
        self.failure_scheduler = FailureScheduler(
            failure_rate_per_hour=2.0
        )  # Average 2 failures per hour
        self.anomaly_detector = Predictor(config.vehicle_id)
        # Rule-based fallback used while the ML window is warming up (first 10 ticks)
        self._rule_detector = AnomalyDetector(config.vehicle_id)
        self._tick_count: int = 0

        logger.info(
            "agent_initialized",
            vehicle_id=config.vehicle_id,
            vehicle_type=config.vehicle_type.value,
            fleet_id=config.fleet_id,
        )

    async def start(self) -> None:
        """
        Start the vehicle agent.

        Establishes Redis connection, prepares for operation, and starts the
        background command listener task.

        Raises:
            RuntimeError: If agent is already running
            redis.ConnectionError: If Redis connection fails
        """
        if self.running:
            raise RuntimeError("Agent is already running")

        logger.info("agent_starting", vehicle_id=self.config.vehicle_id)

        # Connect to Redis
        await self.redis_client.connect()

        self.running = True

        # Start background task that listens for dispatch commands
        self._command_listener_task = asyncio.create_task(
            self._listen_for_commands(),
            name=f"cmd-listener-{self.config.vehicle_id}",
        )

        logger.info("agent_started", vehicle_id=self.config.vehicle_id)

    async def stop(self) -> None:
        """Stop the vehicle agent gracefully."""
        if not self.running:
            return

        logger.info("agent_stopping", vehicle_id=self.config.vehicle_id)

        self.running = False

        # Cancel the command listener task
        if self._command_listener_task and not self._command_listener_task.done():
            self._command_listener_task.cancel()
            try:
                await self._command_listener_task
            except asyncio.CancelledError:
                pass

        # Disconnect from Redis
        await self.redis_client.disconnect()

        logger.info(
            "agent_stopped",
            vehicle_id=self.config.vehicle_id,
            total_uptime_seconds=self.uptime_seconds,
        )

    async def run(self) -> None:
        """
        Main agent loop.

        Runs continuously at the configured telemetry frequency, generating
        and publishing telemetry data. Handles graceful shutdown on signals.

        Example:
            >>> agent = VehicleAgent(config)
            >>> await agent.run()  # Runs until stopped
        """
        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()

        def signal_handler() -> None:
            logger.info("shutdown_signal_received", vehicle_id=self.config.vehicle_id)
            self.running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        # Start the agent
        await self.start()

        # Calculate tick interval from frequency
        tick_interval = 1.0 / self.config.telemetry_frequency_hz

        logger.info(
            "agent_running",
            vehicle_id=self.config.vehicle_id,
            frequency_hz=self.config.telemetry_frequency_hz,
            tick_interval_sec=tick_interval,
        )

        # Main event loop
        try:
            while self.running:
                tick_start = asyncio.get_event_loop().time()

                # Execute one tick
                await self._tick()

                # Calculate sleep time to maintain frequency
                tick_elapsed = asyncio.get_event_loop().time() - tick_start
                sleep_time = max(0, tick_interval - tick_elapsed)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                # Update uptime
                self.uptime_seconds += tick_interval

        except Exception as e:
            logger.error(
                "agent_error",
                vehicle_id=self.config.vehicle_id,
                error=str(e),
                exc_info=True,
            )
            raise
        finally:
            # Ensure cleanup happens
            await self.stop()

    async def _tick(self) -> None:
        """
        Execute one tick of the main loop.

        This method is called every tick interval and:
        1. Evaluates automatic failure scheduling
        2. Handles maintenance / repair timer (if vehicle is in MAINTENANCE)
        3. Generates telemetry
        4. Applies active failure scenarios
        5. Detects anomalies and generates alerts; triggers repair if critical
        6. Publishes telemetry and alerts to Redis
        """
        try:
            # 1. Evaluate automatic failure scheduling (skip while in repair)
            if self.operational_status != OperationalStatus.MAINTENANCE:
                dt_hours = 1.0 / (self.config.telemetry_frequency_hz * 3600.0)
                self.failure_scheduler.tick(dt_hours, self.failure_injector.activate_scenario)

            # 2. Handle ongoing repair timer
            if self.operational_status == OperationalStatus.MAINTENANCE:
                await self._check_repair_complete()
                # Still publish telemetry so the dashboard shows the vehicle
                telemetry = self.telemetry_generator.generate(self.operational_status)
                await self.redis_client.publish_telemetry(telemetry)
                return

            # 3. Generate baseline telemetry
            telemetry = self.telemetry_generator.generate(self.operational_status)

            # 4. Apply active failure scenarios
            telemetry = self.failure_injector.apply_failures(telemetry)

            # 5. Detect anomalies and generate alerts.
            #    During the first 10 ticks the ML sliding window is not full;
            #    fall back to the rule-based AnomalyDetector until it warms up.
            self._tick_count += 1
            if self._tick_count <= 10:
                alerts = self._rule_detector.analyze(telemetry)
            else:
                alerts = self.anomaly_detector.analyze(telemetry)
                # If ML returns nothing but rules see something, use rules as safety net
                if not alerts:
                    alerts = self._rule_detector.analyze(telemetry)

            # 5a. If a CRITICAL alert is raised and the vehicle has active failures,
            #     send it to MAINTENANCE so it can be repaired and return later.
            if alerts and self.failure_injector.active_scenarios:
                from src.models.enums import AlertSeverity

                if any(a.severity == AlertSeverity.CRITICAL for a in alerts):
                    await self._enter_maintenance()

            # 6. Publish telemetry to Redis
            await self.redis_client.publish_telemetry(telemetry)

            # 7. Publish alerts if any were generated
            for alert in alerts:
                await self.redis_client.publish_alert(alert)
                logger.warning(
                    "alert_generated",
                    vehicle_id=self.config.vehicle_id,
                    alert_id=alert.alert_id,
                    severity=alert.severity.value,
                    component=alert.component,
                )

        except Exception as e:
            # Log error but continue running
            logger.error(
                "tick_error",
                vehicle_id=self.config.vehicle_id,
                error=str(e),
            )
            # Don't raise - we want to keep the agent running

    async def _enter_maintenance(self) -> None:
        """Transition the vehicle to MAINTENANCE and schedule a repair.

        The vehicle will stay in MAINTENANCE for REPAIR_DURATION_SECONDS (±25%
        random jitter), after which it deactivates all failures and returns to IDLE.
        """
        import random

        if self.operational_status == OperationalStatus.MAINTENANCE:
            return  # already in maintenance

        self.operational_status = OperationalStatus.MAINTENANCE
        self.current_emergency_id = None
        self.telemetry_generator.clear_target_location()

        # Jitter ±25 % so not every vehicle finishes at the same time
        jitter = random.uniform(0.75, 1.25)
        self._repair_duration_seconds = REPAIR_DURATION_SECONDS * jitter
        self._repair_started_at = datetime.now(UTC)

        logger.warning(
            "vehicle_entered_maintenance",
            vehicle_id=self.config.vehicle_id,
            repair_duration_seconds=round(self._repair_duration_seconds),
            active_failures=[s.value for s in self.failure_injector.active_scenarios],
        )

    async def _check_repair_complete(self) -> None:
        """Check whether the repair timer has elapsed and restore the vehicle if so."""
        if self._repair_started_at is None:
            return

        elapsed = (datetime.now(UTC) - self._repair_started_at).total_seconds()
        if elapsed < self._repair_duration_seconds:
            return  # still being repaired

        # Repair done — deactivate all failures and return to service
        for scenario in list(self.failure_injector.active_scenarios.keys()):
            self.failure_injector.deactivate_scenario(scenario)

        self.operational_status = OperationalStatus.IDLE
        self._repair_started_at = None
        self._repair_duration_seconds = 0.0

        logger.info(
            "vehicle_repair_complete",
            vehicle_id=self.config.vehicle_id,
        )

        # Publish a "cleared" message so the orchestrator can reset has_active_alert
        await self._publish_alert_cleared()

    async def _publish_alert_cleared(self) -> None:
        """Publish a cleared-alert notification to the orchestrator via Redis."""
        redis_conn = self.redis_client.redis
        if redis_conn is None:
            return
        channel = f"aegis:{self.config.fleet_id}:alerts_cleared:{self.config.vehicle_id}"
        payload = json.dumps(
            {"vehicle_id": self.config.vehicle_id, "cleared_at": datetime.now(UTC).isoformat()}
        )
        try:
            await redis_conn.publish(channel, payload)
            logger.info("alert_cleared_published", vehicle_id=self.config.vehicle_id)
        except Exception as e:
            logger.error(
                "alert_cleared_publish_failed", vehicle_id=self.config.vehicle_id, error=str(e)
            )

    def get_status(self) -> dict[str, Any]:
        """
        Get current agent status.

        Returns:
            Dictionary containing agent status information
        """
        return {
            "vehicle_id": self.config.vehicle_id,
            "vehicle_type": self.config.vehicle_type.value,
            "running": self.running,
            "uptime_seconds": self.uptime_seconds,
            "redis_connected": self.redis_client.is_connected,
            "operational_status": self.operational_status.value,
            "current_emergency_id": self.current_emergency_id,
        }

    async def _listen_for_commands(self) -> None:
        """Subscribe to this vehicle's commands channel and handle incoming commands.

        Runs as a background task alongside the main telemetry loop.
        Subscribes to two channels:

        - ``aegis:{fleet_id}:commands:{vehicle_id}`` — per-vehicle dispatch assignments.
        - ``aegis:dispatch:*:resolved`` — broadcast when an emergency is resolved.

        The method exits cleanly when the task is cancelled or the agent stops.
        """
        redis_conn = self.redis_client.redis
        if redis_conn is None:
            logger.warning("command_listener_no_redis", vehicle_id=self.config.vehicle_id)
            return

        commands_channel = self.config.get_channel_name("commands")
        resolved_pattern = "aegis:dispatch:*:resolved"

        pubsub = redis_conn.pubsub()
        try:
            await pubsub.subscribe(commands_channel)
            await pubsub.psubscribe(resolved_pattern)

            logger.info(
                "command_listener_started",
                vehicle_id=self.config.vehicle_id,
                commands_channel=commands_channel,
            )

            async for raw in pubsub.listen():
                if not self.running:
                    break
                if raw["type"] not in ("message", "pmessage"):
                    continue
                data = raw.get("data", "")
                if not data or not isinstance(data, str):
                    continue
                await self._handle_command(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                "command_listener_error",
                vehicle_id=self.config.vehicle_id,
                error=str(e),
            )
        finally:
            try:
                await pubsub.unsubscribe()
                await pubsub.punsubscribe()
                await pubsub.close()
            except Exception:
                pass

    async def _handle_command(self, raw_data: str) -> None:
        """Parse and react to a single command payload.

        Supports two commands:

        - ``dispatch`` — transitions the vehicle to EN_ROUTE and records the
          emergency ID.
        - ``resolve`` — transitions the vehicle back to IDLE and clears the
          emergency ID (only if this vehicle was assigned to that emergency).

        Args:
            raw_data: Raw JSON string received from the Redis channel.
        """
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as e:
            logger.warning(
                "command_parse_error",
                vehicle_id=self.config.vehicle_id,
                error=str(e),
            )
            return

        command = payload.get("command", "")

        if command == "dispatch":
            emergency_id = payload.get("emergency_id")
            emergency_type = payload.get("emergency_type", "unknown")
            location = payload.get("location", {})
            target_lat = location.get("latitude")
            target_lon = location.get("longitude")

            # Don't accept dispatches while under repair
            if self.operational_status == OperationalStatus.MAINTENANCE:
                logger.warning(
                    "dispatch_ignored_in_maintenance",
                    vehicle_id=self.config.vehicle_id,
                    emergency_id=emergency_id,
                )
                return

            self.operational_status = OperationalStatus.EN_ROUTE
            self.current_emergency_id = emergency_id

            if target_lat is not None and target_lon is not None:
                self.telemetry_generator.set_target_location(target_lat, target_lon)

            logger.info(
                "dispatch_command_received",
                vehicle_id=self.config.vehicle_id,
                emergency_id=emergency_id,
                emergency_type=emergency_type,
                target_lat=target_lat,
                target_lon=target_lon,
                new_status=self.operational_status.value,
            )

        elif command == "resolve":
            emergency_id = payload.get("emergency_id")
            released = payload.get("released_vehicles", [])
            if self.config.vehicle_id in released:
                self.operational_status = OperationalStatus.IDLE
                self.current_emergency_id = None
                self.telemetry_generator.clear_target_location()
                logger.info(
                    "resolve_command_received",
                    vehicle_id=self.config.vehicle_id,
                    emergency_id=emergency_id,
                    new_status=self.operational_status.value,
                )

        else:
            logger.debug(
                "unknown_command",
                vehicle_id=self.config.vehicle_id,
                command=command,
            )
