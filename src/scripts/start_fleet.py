"""
CLI entry point for fleet simulation.

This script provides the 'aegis-fleet' command for launching multiple vehicle
agents concurrently, simulating a full emergency-vehicle fleet.  All agents
run in the same asyncio event loop and share a single Redis connection pool.
"""

import asyncio
import random
import sys
from typing import Literal

import click
import structlog

from src.core.time import RealClock
from src.infrastructure.redis_bus import RedisMessageBus
from src.models.enums import VehicleType
from src.vehicle_agent.agent import VehicleAgent
from src.vehicle_agent.config import AgentConfig

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
)

logger = structlog.get_logger(__name__)

# Default starting coordinates for each vehicle type (San Francisco area)
_TYPE_DEFAULTS: dict[VehicleType, tuple[float, float]] = {
    VehicleType.AMBULANCE: (37.7749, -122.4194),
    VehicleType.FIRE_TRUCK: (37.7850, -122.4070),
    VehicleType.POLICE: (37.7690, -122.4330),
}

# Map CLI string values to VehicleType enum
_TYPE_MAP: dict[str, VehicleType] = {
    "ambulance": VehicleType.AMBULANCE,
    "fire_truck": VehicleType.FIRE_TRUCK,
    "police": VehicleType.POLICE,
}

# ID prefix per vehicle type
_ID_PREFIX: dict[VehicleType, str] = {
    VehicleType.AMBULANCE: "AMB",
    VehicleType.FIRE_TRUCK: "FIRE",
    VehicleType.POLICE: "POL",
}


def _build_configs(
    vehicle_type: VehicleType,
    count: int,
    fleet_id: str,
    redis_host: str,
    redis_port: int,
    redis_password: str | None,
    telemetry_frequency: float,
    jitter_km: float,
    navigator_provider: Literal["geometric", "osmnx"] = "geometric",
    osmnx_place_name: str = "San Francisco, California, USA",
    osmnx_network_type: Literal["drive", "walk", "bike", "all"] = "drive",
) -> list[AgentConfig]:
    """Build AgentConfig instances for *count* vehicles of *vehicle_type*.

    Each vehicle starts at the default location for its type, offset by a
    small random jitter so they are not all at the same GPS coordinate.

    Args:
        vehicle_type: Type of vehicle to create configs for.
        count: Number of vehicles to create.
        fleet_id: Fleet identifier shared by all agents.
        redis_host: Redis server hostname.
        redis_port: Redis server port.
        redis_password: Optional Redis password.
        telemetry_frequency: Telemetry generation frequency in Hz.
        jitter_km: Maximum random positional spread in kilometres.

    Returns:
        List of AgentConfig instances ready for VehicleAgent construction.
    """
    prefix = _ID_PREFIX[vehicle_type]
    base_lat, base_lon = _TYPE_DEFAULTS[vehicle_type]
    # 1 degree latitude ≈ 111 km
    degree_per_km = 1.0 / 111.0
    configs: list[AgentConfig] = []

    for i in range(1, count + 1):
        lat_offset = random.uniform(-jitter_km, jitter_km) * degree_per_km
        lon_offset = random.uniform(-jitter_km, jitter_km) * degree_per_km
        configs.append(
            AgentConfig(
                vehicle_id=f"{prefix}-{i:03d}",
                vehicle_type=vehicle_type,
                fleet_id=fleet_id,
                redis_host=redis_host,
                redis_port=redis_port,
                redis_password=redis_password,
                telemetry_frequency_hz=telemetry_frequency,
                navigator_provider=navigator_provider,
                osmnx_place_name=osmnx_place_name,
                osmnx_network_type=osmnx_network_type,
                initial_latitude=base_lat + lat_offset,
                initial_longitude=base_lon + lon_offset,
            )
        )

    return configs


async def _run_fleet(agents: list[VehicleAgent]) -> None:
    """Run all agents concurrently until all complete or an error occurs.

    Args:
        agents: List of VehicleAgent instances to run.
    """
    tasks = [asyncio.create_task(agent.run(), name=agent.config.vehicle_id) for agent in agents]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        # Cancel all remaining tasks on shutdown
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _build_vehicle_agents(configs: list[AgentConfig]) -> list[VehicleAgent]:
    """Build vehicle agents with explicit dependency wiring."""
    agents: list[VehicleAgent] = []
    for cfg in configs:
        bus = RedisMessageBus(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password,
            db=cfg.redis_db,
        )
        agents.append(VehicleAgent(cfg, message_bus=bus, clock=RealClock()))
    return agents


@click.command()
@click.option(
    "--ambulances",
    default=2,
    type=int,
    show_default=True,
    help="Number of ambulance agents to spawn.",
)
@click.option(
    "--fire-trucks",
    default=1,
    type=int,
    show_default=True,
    help="Number of fire-truck agents to spawn.",
)
@click.option(
    "--police",
    default=1,
    type=int,
    show_default=True,
    help="Number of police agents to spawn.",
)
@click.option(
    "--fleet-id",
    default="fleet01",
    show_default=True,
    help="Fleet identifier shared by all agents.",
)
@click.option(
    "--redis-host",
    default="localhost",
    show_default=True,
    help="Redis server hostname.",
)
@click.option(
    "--redis-port",
    default=6379,
    type=int,
    show_default=True,
    help="Redis server port.",
)
@click.option(
    "--redis-password",
    default=None,
    help="Redis password (optional).",
)
@click.option(
    "--telemetry-frequency",
    default=1.0,
    type=float,
    show_default=True,
    help="Telemetry generation frequency in Hz for all agents.",
)
@click.option(
    "--jitter-km",
    default=5.0,
    type=float,
    show_default=True,
    help="Maximum random positional spread (km) around the default start location.",
)
@click.option(
    "--navigator-provider",
    type=click.Choice(["geometric", "osmnx"], case_sensitive=False),
    default="geometric",
    show_default=True,
    help="Movement provider for all vehicles.",
)
@click.option(
    "--osmnx-place-name",
    default="San Francisco, California, USA",
    show_default=True,
    help="OSM place to load for road routing when using osmnx.",
)
@click.option(
    "--osmnx-network-type",
    default="drive",
    type=click.Choice(["drive", "walk", "bike", "all"], case_sensitive=False),
    show_default=True,
    help="OSMnx network type when using osmnx.",
)
def main(
    ambulances: int,
    fire_trucks: int,
    police: int,
    fleet_id: str,
    redis_host: str,
    redis_port: int,
    redis_password: str | None,
    telemetry_frequency: float,
    jitter_km: float,
    navigator_provider: str,
    osmnx_place_name: str,
    osmnx_network_type: str,
) -> None:
    """
    Start a simulated fleet of emergency vehicle agents for Project AEGIS.

    Launches multiple VehicleAgent instances concurrently (same event loop).
    Each agent generates synthetic telemetry and listens for dispatch commands
    from the orchestrator.

    Use Ctrl+C for graceful shutdown of the entire fleet.

    Examples:

        \\b
        # Default fleet: 2 ambulances, 1 fire truck, 1 police unit
        aegis-fleet

        \\b
        # Custom fleet composition
        aegis-fleet --ambulances 4 --fire-trucks 2 --police 3

        \\b
        # Custom Redis and frequency
        aegis-fleet --redis-host redis.example.com --telemetry-frequency 2.0
    """
    total = ambulances + fire_trucks + police
    if total == 0:
        click.echo("No vehicles requested. Use --ambulances/--fire-trucks/--police.", err=True)
        sys.exit(1)

    # Build all configs
    all_configs: list[AgentConfig] = []
    for vtype, count in [
        (VehicleType.AMBULANCE, ambulances),
        (VehicleType.FIRE_TRUCK, fire_trucks),
        (VehicleType.POLICE, police),
    ]:
        if count > 0:
            all_configs.extend(
                _build_configs(
                    vehicle_type=vtype,
                    count=count,
                    fleet_id=fleet_id,
                    redis_host=redis_host,
                    redis_port=redis_port,
                    redis_password=redis_password,
                    telemetry_frequency=telemetry_frequency,
                    jitter_km=jitter_km,
                    navigator_provider=navigator_provider.lower(),
                    osmnx_place_name=osmnx_place_name,
                    osmnx_network_type=osmnx_network_type.lower(),
                )
            )

    agents = _build_vehicle_agents(all_configs)

    click.echo("🚨 Project AEGIS - Fleet Simulation")
    click.echo(f"   Fleet ID    : {fleet_id}")
    click.echo(f"   Redis       : {redis_host}:{redis_port}")
    click.echo(f"   Ambulances  : {ambulances}")
    click.echo(f"   Fire trucks : {fire_trucks}")
    click.echo(f"   Police      : {police}")
    click.echo(f"   Total       : {total} vehicles")
    click.echo(f"   Frequency   : {telemetry_frequency} Hz")
    click.echo(f"   Navigator   : {navigator_provider.lower()}")
    click.echo()
    click.echo("Press Ctrl+C to stop")
    click.echo()

    try:
        asyncio.run(_run_fleet(agents))
    except KeyboardInterrupt:
        click.echo()
        click.echo(f"✓ Fleet ({fleet_id}) shutdown complete")
    except Exception as e:
        logger.error("fleet_crashed", error=str(e), exc_info=True)
        click.echo(f"❌ Fleet crashed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
