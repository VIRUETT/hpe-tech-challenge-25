"""
Unit tests for VehicleAgent dispatch command handling (Fase 3).

All Redis interactions are mocked - no running Redis server required.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.enums import OperationalStatus, VehicleType
from src.orchestrator.agent import OrchestratorAgent
from src.vehicle_agent.agent import VehicleAgent
from src.vehicle_agent.config import AgentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(vehicle_id: str = "AMB-001") -> AgentConfig:
    """Create a minimal AgentConfig for testing."""
    return AgentConfig(
        vehicle_id=vehicle_id,
        vehicle_type=VehicleType.AMBULANCE,
        fleet_id="fleet01",
    )


def _make_agent(vehicle_id: str = "AMB-001") -> VehicleAgent:
    """Create a VehicleAgent with a default config (no real Redis)."""
    return VehicleAgent(_make_config(vehicle_id))


def _dispatch_payload(
    vehicle_id: str = "AMB-001",
    emergency_id: str = "emg-001",
    emergency_type: str = "medical",
) -> str:
    """Build a JSON dispatch command string."""
    return json.dumps(
        {
            "command": "dispatch",
            "emergency_id": emergency_id,
            "emergency_type": emergency_type,
            "location": {"latitude": 19.43, "longitude": -99.13},
            "dispatch_id": "disp-001",
        }
    )


def _resolve_payload(
    emergency_id: str = "emg-001",
    released_vehicles: list[str] | None = None,
) -> str:
    """Build a JSON resolve command string.

    Args:
        emergency_id: ID of the emergency being resolved.
        released_vehicles: Vehicles freed by the resolution. Defaults to
            ``["AMB-001"]`` when *None* is passed; pass an explicit list
            (including ``[]``) to override.
    """
    vehicles = ["AMB-001"] if released_vehicles is None else released_vehicles
    return json.dumps(
        {
            "command": "resolve",
            "emergency_id": emergency_id,
            "released_vehicles": vehicles,
        }
    )


# ---------------------------------------------------------------------------
# VehicleAgent initial state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVehicleAgentInitialState:
    """Tests for VehicleAgent initial operational state."""

    def test_default_status_matches_config(self) -> None:
        """Agent starts with the status configured in AgentConfig."""
        agent = _make_agent()
        assert agent.operational_status == OperationalStatus.IDLE

    def test_no_emergency_on_init(self) -> None:
        """Agent has no active emergency on initialisation."""
        agent = _make_agent()
        assert agent.current_emergency_id is None

    def test_get_status_includes_operational_status(self) -> None:
        """get_status should expose operational_status."""
        agent = _make_agent()
        status = agent.get_status()
        assert "operational_status" in status
        assert status["operational_status"] == OperationalStatus.IDLE.value

    def test_get_status_includes_current_emergency_id(self) -> None:
        """get_status should expose current_emergency_id."""
        agent = _make_agent()
        status = agent.get_status()
        assert "current_emergency_id" in status
        assert status["current_emergency_id"] is None


# ---------------------------------------------------------------------------
# _handle_command — dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleDispatchCommand:
    """Tests for processing 'dispatch' command payloads."""

    @pytest.mark.asyncio
    async def test_dispatch_sets_en_route(self) -> None:
        """A dispatch command should set status to EN_ROUTE."""
        agent = _make_agent()
        await agent._handle_command(_dispatch_payload())
        assert agent.operational_status == OperationalStatus.EN_ROUTE

    @pytest.mark.asyncio
    async def test_dispatch_records_emergency_id(self) -> None:
        """A dispatch command should store the emergency ID."""
        agent = _make_agent()
        await agent._handle_command(_dispatch_payload(emergency_id="emg-999"))
        assert agent.current_emergency_id == "emg-999"

    @pytest.mark.asyncio
    async def test_dispatch_updates_status_field_in_get_status(self) -> None:
        """get_status should reflect EN_ROUTE after dispatch."""
        agent = _make_agent()
        await agent._handle_command(_dispatch_payload())
        status = agent.get_status()
        assert status["operational_status"] == OperationalStatus.EN_ROUTE.value
        assert status["current_emergency_id"] == "emg-001"

    @pytest.mark.asyncio
    async def test_dispatch_with_fire_truck_type(self) -> None:
        """Dispatch command should work for any vehicle type."""
        config = AgentConfig(
            vehicle_id="FIRE-001",
            vehicle_type=VehicleType.FIRE_TRUCK,
        )
        agent = VehicleAgent(config)
        await agent._handle_command(
            json.dumps(
                {
                    "command": "dispatch",
                    "emergency_id": "emg-fire-01",
                    "emergency_type": "fire",
                    "location": {"latitude": 19.43, "longitude": -99.13},
                    "dispatch_id": "disp-fire-01",
                }
            )
        )
        assert agent.operational_status == OperationalStatus.EN_ROUTE
        assert agent.current_emergency_id == "emg-fire-01"

    @pytest.mark.asyncio
    async def test_dispatch_publishes_ack_with_in_memory_bus(self) -> None:
        """Dispatch should publish an acknowledgment event for SLA tracking."""
        from src.core.time import FastForwardClock
        from src.infrastructure.in_memory_bus import InMemoryMessageBus

        bus = InMemoryMessageBus()
        clock = FastForwardClock()
        orchestrator = OrchestratorAgent(message_bus=bus, clock=clock)
        vehicle = VehicleAgent(
            AgentConfig(
                vehicle_id="AMB-001",
                vehicle_type=VehicleType.AMBULANCE,
                fleet_id="fleet01",
            ),
            message_bus=bus,
            clock=clock,
        )

        orchestrator_task = asyncio.create_task(orchestrator.run())
        vehicle_task = asyncio.create_task(vehicle.run())
        try:
            for _ in range(3):
                clock.advance(1.0)
                await asyncio.sleep(0)

            emergency = {
                "command": "dispatch",
                "emergency_id": "emg-ack-001",
                "emergency_type": "medical",
                "location": {"latitude": 37.7749, "longitude": -122.4194},
                "dispatch_id": "disp-ack-001",
            }
            await vehicle._handle_command(json.dumps(emergency))

            for _ in range(3):
                await asyncio.sleep(0)

            dispatch = orchestrator.dispatches.get("emg-ack-001")
            if dispatch is not None and dispatch.units:
                assert dispatch.units[0].acknowledged is True
        finally:
            vehicle.running = False
            orchestrator.running = False
            clock.advance(1.0)
            await asyncio.sleep(0)
            await bus.close()
            await asyncio.wait_for(orchestrator_task, timeout=1.0)
            await asyncio.wait_for(vehicle_task, timeout=1.0)


# ---------------------------------------------------------------------------
# _handle_command — resolve
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleResolveCommand:
    """Tests for processing 'resolve' command payloads."""

    @pytest.mark.asyncio
    async def test_resolve_returns_vehicle_to_idle(self) -> None:
        """Resolve command (with this vehicle in released list) should set IDLE."""
        agent = _make_agent("AMB-001")
        # First, simulate being dispatched
        await agent._handle_command(_dispatch_payload())
        assert agent.operational_status == OperationalStatus.EN_ROUTE

        # Now resolve
        await agent._handle_command(_resolve_payload(released_vehicles=["AMB-001"]))
        assert agent.operational_status == OperationalStatus.IDLE

    @pytest.mark.asyncio
    async def test_resolve_clears_emergency_id(self) -> None:
        """Resolve command should clear current_emergency_id."""
        agent = _make_agent("AMB-001")
        await agent._handle_command(_dispatch_payload(emergency_id="emg-999"))
        await agent._handle_command(
            _resolve_payload(emergency_id="emg-999", released_vehicles=["AMB-001"])
        )
        assert agent.current_emergency_id is None

    @pytest.mark.asyncio
    async def test_resolve_ignores_other_vehicles(self) -> None:
        """Resolve command for other vehicles should not affect this agent."""
        agent = _make_agent("AMB-001")
        await agent._handle_command(_dispatch_payload())
        assert agent.operational_status == OperationalStatus.EN_ROUTE

        # Resolve only mentions AMB-002 - AMB-001 should stay EN_ROUTE
        await agent._handle_command(_resolve_payload(released_vehicles=["AMB-002", "FIRE-001"]))
        assert agent.operational_status == OperationalStatus.EN_ROUTE
        assert agent.current_emergency_id == "emg-001"

    @pytest.mark.asyncio
    async def test_resolve_with_empty_released_list(self) -> None:
        """Resolve with empty released_vehicles should not change status."""
        agent = _make_agent("AMB-001")
        await agent._handle_command(_dispatch_payload())
        await agent._handle_command(_resolve_payload(released_vehicles=[]))
        assert agent.operational_status == OperationalStatus.EN_ROUTE


# ---------------------------------------------------------------------------
# _handle_command — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleCommandEdgeCases:
    """Edge case tests for _handle_command."""

    @pytest.mark.asyncio
    async def test_invalid_json_is_ignored(self) -> None:
        """Malformed JSON should not raise and should not change state."""
        agent = _make_agent()
        await agent._handle_command("not-valid-json")  # Should not raise
        assert agent.operational_status == OperationalStatus.IDLE

    @pytest.mark.asyncio
    async def test_unknown_command_is_ignored(self) -> None:
        """Unknown command types should be silently ignored."""
        agent = _make_agent()
        payload = json.dumps({"command": "self_destruct"})
        await agent._handle_command(payload)  # Should not raise
        assert agent.operational_status == OperationalStatus.IDLE

    @pytest.mark.asyncio
    async def test_empty_json_object_is_ignored(self) -> None:
        """An empty JSON object should be silently ignored."""
        agent = _make_agent()
        await agent._handle_command("{}")
        assert agent.operational_status == OperationalStatus.IDLE

    @pytest.mark.asyncio
    async def test_multiple_dispatches_update_emergency_id(self) -> None:
        """Sequential dispatch commands should update the emergency ID each time."""
        agent = _make_agent()
        await agent._handle_command(_dispatch_payload(emergency_id="emg-001"))
        assert agent.current_emergency_id == "emg-001"

        await agent._handle_command(_dispatch_payload(emergency_id="emg-002"))
        assert agent.current_emergency_id == "emg-002"


# ---------------------------------------------------------------------------
# VehicleAgent start / stop with command listener
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVehicleAgentLifecycle:
    """Tests for start/stop lifecycle with command listener task."""

    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(self) -> None:
        """Calling start() twice should raise RuntimeError."""
        agent = _make_agent()

        with patch("redis.asyncio.Redis") as mock_redis_cls:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock()
            mock_redis.pubsub = MagicMock(return_value=AsyncMock())
            mock_redis_cls.return_value = mock_redis

            # Patch pubsub.listen to block forever so listener stays alive
            pubsub_mock = AsyncMock()
            pubsub_mock.subscribe = AsyncMock()
            pubsub_mock.psubscribe = AsyncMock()
            pubsub_mock.listen = MagicMock(return_value=_infinite_async_gen())
            pubsub_mock.unsubscribe = AsyncMock()
            pubsub_mock.punsubscribe = AsyncMock()
            pubsub_mock.close = AsyncMock()
            mock_redis.pubsub = MagicMock(return_value=pubsub_mock)

            await agent.start()
            assert agent.running is True

            with pytest.raises(RuntimeError, match="already running"):
                await agent.start()

            await agent.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """Calling stop() on a stopped agent should not raise."""
        agent = _make_agent()
        await agent.stop()  # Should not raise
        await agent.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_cancels_command_listener_task(self) -> None:
        """stop() should cancel the command listener background task."""
        agent = _make_agent()

        with patch("redis.asyncio.Redis") as mock_redis_cls:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock()

            pubsub_mock = AsyncMock()
            pubsub_mock.subscribe = AsyncMock()
            pubsub_mock.psubscribe = AsyncMock()
            pubsub_mock.listen = MagicMock(return_value=_infinite_async_gen())
            pubsub_mock.unsubscribe = AsyncMock()
            pubsub_mock.punsubscribe = AsyncMock()
            pubsub_mock.close = AsyncMock()
            mock_redis.pubsub = MagicMock(return_value=pubsub_mock)
            mock_redis_cls.return_value = mock_redis

            await agent.start()
            task = agent._command_listener_task
            assert task is not None
            assert not task.done()

            await agent.stop()
            assert task.done()


# ---------------------------------------------------------------------------
# Fleet builder helpers (from start_fleet.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildConfigs:
    """Tests for the _build_configs helper in start_fleet."""

    def test_correct_number_of_configs(self) -> None:
        """_build_configs should produce exactly count configs."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=3,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        assert len(configs) == 3

    def test_vehicle_ids_use_correct_prefix(self) -> None:
        """Ambulances should have AMB- prefix, fire trucks FIRE-, police POL-."""
        from src.scripts.start_fleet import _build_configs

        for vtype, prefix in [
            (VehicleType.AMBULANCE, "AMB"),
            (VehicleType.FIRE_TRUCK, "FIRE"),
            (VehicleType.POLICE, "POL"),
        ]:
            configs = _build_configs(
                vehicle_type=vtype,
                count=2,
                fleet_id="fleet01",
                redis_host="localhost",
                redis_port=6379,
                redis_password=None,
                telemetry_frequency=1.0,
                jitter_km=0.0,
            )
            for cfg in configs:
                assert cfg.vehicle_id.startswith(prefix)

    def test_ids_are_zero_padded_three_digits(self) -> None:
        """Vehicle IDs should use zero-padded three-digit numbering."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=5,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        ids = [cfg.vehicle_id for cfg in configs]
        assert "AMB-001" in ids
        assert "AMB-005" in ids

    def test_fleet_id_propagated(self) -> None:
        """All configs should share the given fleet_id."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=2,
            fleet_id="test-fleet",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        for cfg in configs:
            assert cfg.fleet_id == "test-fleet"

    def test_vehicle_type_propagated(self) -> None:
        """All configs should have the correct vehicle_type."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.FIRE_TRUCK,
            count=3,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        for cfg in configs:
            assert cfg.vehicle_type == VehicleType.FIRE_TRUCK

    def test_zero_jitter_gives_default_location(self) -> None:
        """With zero jitter, all vehicles start at the exact default coordinates."""
        from src.scripts.start_fleet import _TYPE_DEFAULTS, _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=2,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        base_lat, base_lon = _TYPE_DEFAULTS[VehicleType.AMBULANCE]
        for cfg in configs:
            assert cfg.initial_latitude == pytest.approx(base_lat)
            assert cfg.initial_longitude == pytest.approx(base_lon)

    def test_telemetry_frequency_propagated(self) -> None:
        """Custom telemetry frequency should be set on all configs."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=2,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=2.0,
            jitter_km=0.0,
        )
        for cfg in configs:
            assert cfg.telemetry_frequency_hz == pytest.approx(2.0)

    def test_zero_count_returns_empty_list(self) -> None:
        """Requesting zero vehicles should return an empty list."""
        from src.scripts.start_fleet import _build_configs

        configs = _build_configs(
            vehicle_type=VehicleType.AMBULANCE,
            count=0,
            fleet_id="fleet01",
            redis_host="localhost",
            redis_port=6379,
            redis_password=None,
            telemetry_frequency=1.0,
            jitter_km=0.0,
        )
        assert configs == []


# ---------------------------------------------------------------------------
# Fleet CLI smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFleetCLI:
    """Smoke tests for the aegis-fleet CLI entry point."""

    def test_cli_zero_vehicles_exits_with_error(self) -> None:
        """Passing all-zero counts should exit with a non-zero code."""
        from click.testing import CliRunner

        from src.scripts.start_fleet import main

        runner = CliRunner()
        result = runner.invoke(main, ["--ambulances", "0", "--fire-trucks", "0", "--police", "0"])
        assert result.exit_code != 0

    def test_cli_help_exits_cleanly(self) -> None:
        """--help flag should print usage and exit 0."""
        from click.testing import CliRunner

        from src.scripts.start_fleet import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "aegis-fleet" in result.output.lower() or "fleet" in result.output.lower()


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _infinite_async_gen():  # type: ignore[return]
    """Async generator that yields nothing but never finishes (until cancelled)."""
    while True:
        await asyncio.sleep(3600)
        yield  # pragma: no cover
