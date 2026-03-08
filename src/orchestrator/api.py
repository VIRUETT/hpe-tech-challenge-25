"""
FastAPI REST + WebSocket API for the AEGIS Orchestrator.

Exposes endpoints for:
- POST /emergencies     Register a new emergency and trigger dispatch
- GET  /emergencies     List all emergencies
- GET  /emergencies/{id} Get a specific emergency with its dispatch
- POST /emergencies/{id}/resolve  Resolve an emergency
- GET  /fleet           Current fleet state
- GET  /health          Liveness check
- WS  /ws              WebSocket stream of real-time events
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.core.time import FastForwardClock
from src.models.emergency import (
    EMERGENCY_UNITS_DEFAULTS,
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    UnitsRequired,
)
from src.models.vehicle import Location
from src.orchestrator.agent import OrchestratorAgent
from src.orchestrator.emergency_prediction_generator import EmergencyGenerator
from src.orchestrator.historical_injector import HistoricalCrimeInjector
from src.storage.database import db

logger = structlog.get_logger(__name__)

MINUTES_PER_TICK = 60
SECOND_BEFORE_UPDATE = 3.0

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class EmergencyCreateRequest(BaseModel):
    """Payload for POST /emergencies."""

    emergency_type: EmergencyType
    severity: EmergencySeverity = EmergencySeverity.HIGH
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: str | None = None
    description: str
    units_required: UnitsRequired | None = Field(
        None, description="Override default units. If None, uses type defaults."
    )
    reported_by: str = "operator"


class EmergencyResponse(BaseModel):
    """Response for emergency endpoints."""

    emergency_id: str
    emergency_type: str
    status: str
    severity: int
    latitude: float
    longitude: float
    address: str | None
    description: str
    units_required: dict[str, int]
    reported_by: str
    created_at: datetime
    dispatched_at: datetime | None
    resolved_at: datetime | None
    dismissed_at: datetime | None
    dispatch_id: str | None
    assigned_vehicles: list[str]


class FleetResponse(BaseModel):
    """Response for GET /fleet."""

    summary: dict[str, Any]
    vehicles: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections for real-time broadcasting."""

    def __init__(self) -> None:
        """Initialize with an empty connections list."""
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            ws: The WebSocket connection to add.
        """
        await ws.accept()
        self._active.append(ws)
        logger.info("ws_client_connected", total=len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection.

        Args:
            ws: The WebSocket connection to remove.
        """
        if ws in self._active:
            self._active.remove(ws)
        logger.info("ws_client_disconnected", total=len(self._active))

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        """Send a JSON event to all connected clients.

        Silently removes clients that fail to receive.

        Args:
            event_type: Event type label (e.g. 'emergency.dispatched').
            data: Event payload dict.
        """
        if not self._active:
            return
        message = json.dumps(
            {"event": event_type, "data": data, "ts": datetime.now(UTC).isoformat()}
        )
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(orchestrator: OrchestratorAgent) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        orchestrator: A fully initialized (but not yet started) OrchestratorAgent.

    Returns:
        Configured FastAPI application instance.
    """
    ws_manager = ConnectionManager()

    # Inject the WebSocket broadcast callback so the orchestrator can push
    # live telemetry snapshots to all connected dashboard clients.
    orchestrator._ws_broadcast = ws_manager.broadcast

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        db.connect()

        # Override the orchestrator's clock if it was initialized with RealClock
        sim_start_time = datetime(2026, 3, 6, 18, 0, tzinfo=UTC)
        shared_clock = FastForwardClock(start_at=sim_start_time)
        orchestrator._clock = shared_clock

        task = asyncio.create_task(_run_orchestrator(orchestrator))

        # Start Historical Injector
        historical_injector = HistoricalCrimeInjector(
            orchestrator, clock=shared_clock, check_interval_seconds=1800.0
        )
        hist_task = asyncio.create_task(historical_injector.start())

        # Start AI Predictor
        ai_generator = EmergencyGenerator(
            orchestrator, clock=shared_clock, check_interval_seconds=1800.0
        )
        ai_gen_task = asyncio.create_task(ai_generator.start())

        # Time Machine Driver: Advances the FastForwardClock 30 mins every 3 real seconds
        async def _drive_clock():
            while not orchestrator.running:
                await asyncio.sleep(0.1)

            while orchestrator.running:
                await asyncio.sleep(3.0)
                shared_clock.advance(1800.0)

        clock_task = asyncio.create_task(_drive_clock())

        yield

        # Teardown
        orchestrator.running = False
        ai_generator.stop()
        historical_injector.stop()

        task.cancel()
        ai_gen_task.cancel()
        hist_task.cancel()
        clock_task.cancel()

        await orchestrator.stop()
        await db.disconnect()

    async def _run_orchestrator(orch: OrchestratorAgent) -> None:
        """Run the orchestrator Redis listener loop."""
        try:
            await orch.start()
            async for raw in orch._bus.subscribe_patterns(
                "aegis:*:telemetry:*",
                "aegis:*:alerts:*",
                "aegis:*:alerts_cleared:*",
                "aegis:emergencies:new",
                "aegis:*:vehicles:register",
            ):
                if not orch.running:
                    break
                await orch._handle_raw_message(raw)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("orchestrator_listener_error", error=str(e))

    app = FastAPI(
        title="AEGIS Orchestrator API",
        description="Emergency vehicle dispatch and fleet management",
        version="0.1.0",
        lifespan=lifespan,
    )

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness check.

        Returns:
            Status dict with 'ok' status.
        """
        return {"status": "ok"}

    # -----------------------------------------------------------------------
    # Fleet
    # -----------------------------------------------------------------------

    @app.get("/fleet", response_model=FleetResponse, tags=["fleet"])
    async def get_fleet() -> FleetResponse:
        """Get current fleet state.

        Returns:
            Summary and per-vehicle details.
        """
        summary = orchestrator.get_fleet_summary()
        summary["simulated_time"] = orchestrator._clock.now().isoformat()
        vehicles = []
        for snap in orchestrator.fleet.values():
            vehicles.append(
                {
                    "vehicle_id": snap.vehicle_id,
                    "vehicle_type": snap.vehicle_type.value,
                    "operational_status": snap.operational_status.value,
                    "is_available": snap.is_available,
                    "current_emergency_id": snap.current_emergency_id,
                    "last_seen_at": snap.last_seen_at.isoformat(),
                    "battery_voltage": snap.battery_voltage,
                    "fuel_level_percent": snap.fuel_level_percent,
                    "engine_temp_celsius": snap.engine_temp_celsius,
                    "oil_pressure_bar": snap.oil_pressure_bar,
                    "vibration_ms2": snap.vibration_ms2,
                    "brake_pad_mm": snap.brake_pad_mm,
                    "has_active_alert": snap.has_active_alert,
                    "location": (snap.location.model_dump(mode="json") if snap.location else None),
                }
            )
        return FleetResponse(summary=summary, vehicles=vehicles)

    @app.get("/alerts", tags=["fleet"])
    async def get_alerts() -> list[dict[str, Any]]:
        """Get all currently active predictive maintenance alerts.

        Returns one entry per vehicle that has an active alert, with full
        PredictiveAlert details.

        Returns:
            List of alert dicts, newest vehicles first.
        """
        result = []
        for vehicle_id, alert in orchestrator.active_alerts.items():
            result.append(
                {
                    "alert_id": alert.alert_id,
                    "vehicle_id": vehicle_id,
                    "timestamp": alert.timestamp.isoformat(),
                    "severity": alert.severity.value,
                    "category": alert.category.value,
                    "component": alert.component,
                    "failure_probability": alert.failure_probability,
                    "confidence": alert.confidence,
                    "predicted_failure_min_hours": alert.predicted_failure_min_hours,
                    "predicted_failure_max_hours": alert.predicted_failure_max_hours,
                    "predicted_failure_likely_hours": alert.predicted_failure_likely_hours,
                    "can_complete_current_mission": alert.can_complete_current_mission,
                    "recommended_action": alert.recommended_action,
                    "safe_to_operate": alert.safe_to_operate,
                    "contributing_factors": alert.contributing_factors,
                    "related_telemetry": alert.related_telemetry,
                }
            )
        return result

    @app.get("/crime-predictions", tags=["fleet"])
    async def get_crime_predictions() -> list[dict[str, Any]]:
        """Get all currently active AI crime predictions."""
        result = []
        for prediction in orchestrator.active_crime_predictions.values():
            result.append(
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
                }
            )
        result.sort(key=lambda item: item["timestamp"], reverse=True)
        return result

    # -----------------------------------------------------------------------
    # Emergencies
    # -----------------------------------------------------------------------

    @app.post("/emergencies", tags=["emergencies"])
    async def create_emergency(request: EmergencyCreateRequest) -> dict[str, Any]:
        """Register a new emergency and dispatch the nearest available units.

        Args:
            request: Emergency creation payload.

        Returns:
            Emergency and dispatch details.
        """
        # Build Location for the incident
        location = Location(
            latitude=request.latitude,
            longitude=request.longitude,
            timestamp=datetime.now(UTC),
        )

        # Use type-based defaults if no explicit units provided
        units_required = request.units_required or EMERGENCY_UNITS_DEFAULTS[request.emergency_type]

        emergency = Emergency(
            emergency_type=request.emergency_type,
            severity=request.severity,
            location=location,
            address=request.address,
            description=request.description,
            units_required=units_required,
            reported_by=request.reported_by,
        )

        dispatch = await orchestrator.process_emergency(emergency)

        response_data = _emergency_to_dict(emergency, dispatch)

        # Broadcast to WebSocket clients
        await ws_manager.broadcast("emergency.dispatched", response_data)

        return response_data

    @app.get("/emergencies", tags=["emergencies"])
    async def list_emergencies(
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all emergencies, optionally filtered by status.

        Args:
            status: Optional status filter (e.g. 'pending', 'dispatched').

        Returns:
            List of emergency dicts.
        """
        result = []
        for em in orchestrator.emergencies.values():
            if status and em.status.value != status:
                continue
            dispatch = orchestrator.dispatches.get(em.emergency_id)
            result.append(_emergency_to_dict(em, dispatch))
        return result

    @app.get("/emergencies/{emergency_id}", tags=["emergencies"])
    async def get_emergency(emergency_id: str) -> dict[str, Any]:
        """Get a specific emergency by ID.

        Args:
            emergency_id: The unique emergency identifier.

        Returns:
            Emergency details with dispatch info.

        Raises:
            HTTPException: 404 if emergency not found.
        """
        emergency = orchestrator.emergencies.get(emergency_id)
        if not emergency:
            raise HTTPException(status_code=404, detail="Emergency not found")
        dispatch = orchestrator.dispatches.get(emergency_id)
        return _emergency_to_dict(emergency, dispatch)

    @app.post("/emergencies/{emergency_id}/resolve", tags=["emergencies"])
    async def resolve_emergency(emergency_id: str) -> dict[str, Any]:
        """Resolve an emergency and release assigned units back to IDLE.

        Args:
            emergency_id: The unique emergency identifier.

        Returns:
            Resolved emergency details and list of released vehicles.

        Raises:
            HTTPException: 404 if emergency not found.
            HTTPException: 409 if emergency is already resolved.
        """
        emergency = orchestrator.emergencies.get(emergency_id)
        if not emergency:
            raise HTTPException(status_code=404, detail="Emergency not found")
        if emergency.status in (EmergencyStatus.RESOLVED, EmergencyStatus.DISMISSED):
            raise HTTPException(status_code=409, detail="Emergency already closed")

        released = await orchestrator.resolve_emergency(emergency_id)

        response_data = {
            **_emergency_to_dict(emergency, orchestrator.dispatches.get(emergency_id)),
            "released_vehicles": released,
        }

        await ws_manager.broadcast("emergency.resolved", response_data)
        return response_data

    # -----------------------------------------------------------------------
    # WebSocket
    # -----------------------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """WebSocket endpoint for real-time event streaming.

        Clients receive JSON events for emergency dispatches, resolutions,
        and other real-time updates.
        """
        await ws_manager.connect(ws)
        try:
            while True:
                # Keep alive - wait for client messages (ping/pong)
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    return app


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _emergency_to_dict(
    emergency: Emergency,
    dispatch: Any | None,
) -> dict[str, Any]:
    """Serialize an emergency and its dispatch to a response dict.

    Args:
        emergency: The emergency object.
        dispatch: The associated Dispatch (may be None).

    Returns:
        Dict suitable for JSON API responses.
    """
    return {
        "emergency_id": emergency.emergency_id,
        "emergency_type": emergency.emergency_type.value,
        "status": emergency.status.value,
        "severity": emergency.severity.value,
        "latitude": emergency.location.latitude,
        "longitude": emergency.location.longitude,
        "address": emergency.address,
        "description": emergency.description,
        "units_required": {
            "ambulances": emergency.units_required.ambulances,
            "fire_trucks": emergency.units_required.fire_trucks,
            "police": emergency.units_required.police,
        },
        "reported_by": emergency.reported_by,
        "created_at": emergency.created_at.isoformat(),
        "dispatched_at": (emergency.dispatched_at.isoformat() if emergency.dispatched_at else None),
        "resolved_at": (emergency.resolved_at.isoformat() if emergency.resolved_at else None),
        "dismissed_at": (emergency.dismissed_at.isoformat() if emergency.dismissed_at else None),
        "dispatch_id": dispatch.dispatch_id if dispatch else None,
        "assigned_vehicles": dispatch.vehicle_ids if dispatch else [],
    }
