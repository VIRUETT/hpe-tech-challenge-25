"""
CLI entry point for starting a single vehicle agent.

This script provides the 'aegis-vehicle' command for running individual
vehicle agents for simulation and testing.
"""

import asyncio
import sys

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


@click.command()
@click.option(
    "--vehicle-id",
    required=True,
    help="Unique vehicle identifier (e.g., AMB-001, FIRE-042)",
)
@click.option(
    "--vehicle-type",
    type=click.Choice(["ambulance", "fire_truck", "police"], case_sensitive=False),
    required=True,
    help="Type of emergency vehicle",
)
@click.option(
    "--fleet-id",
    default="fleet01",
    help="Fleet identifier (default: fleet01)",
)
@click.option(
    "--redis-host",
    default="localhost",
    help="Redis server hostname (default: localhost)",
)
@click.option(
    "--redis-port",
    default=6379,
    type=int,
    help="Redis server port (default: 6379)",
)
@click.option(
    "--redis-password",
    default=None,
    help="Redis password (optional)",
)
@click.option(
    "--telemetry-frequency",
    default=1.0,
    type=float,
    help="Telemetry generation frequency in Hz (default: 1.0)",
)
@click.option(
    "--navigator-provider",
    type=click.Choice(["geometric", "osmnx"], case_sensitive=False),
    default="geometric",
    help="Movement provider to use (default: geometric)",
)
@click.option(
    "--osmnx-place-name",
    default="San Francisco, California, USA",
    help="OSM place to load for road routing when using osmnx",
)
@click.option(
    "--osmnx-network-type",
    default="drive",
    type=click.Choice(["drive", "walk", "bike", "all"], case_sensitive=False),
    help="OSMnx network type (default: drive)",
)
@click.option(
    "--latitude",
    default=37.7749,
    type=float,
    help="Starting latitude (default: San Francisco)",
)
@click.option(
    "--longitude",
    default=-122.4194,
    type=float,
    help="Starting longitude (default: San Francisco)",
)
def main(
    vehicle_id: str,
    vehicle_type: str,
    fleet_id: str,
    redis_host: str,
    redis_port: int,
    redis_password: str | None,
    telemetry_frequency: float,
    navigator_provider: str,
    osmnx_place_name: str,
    osmnx_network_type: str,
    latitude: float,
    longitude: float,
) -> None:
    """
    Start a single vehicle agent for Project AEGIS.

    The agent will generate synthetic telemetry data and publish it to Redis
    at the specified frequency. Use Ctrl+C for graceful shutdown.

    Examples:

        \b
        # Start an ambulance
        aegis-vehicle --vehicle-id AMB-001 --vehicle-type ambulance

        \b
        # Start a fire truck with custom Redis connection
        aegis-vehicle --vehicle-id FIRE-042 --vehicle-type fire_truck \\
            --redis-host redis.example.com --redis-port 6380

        \b
        # Start with high-frequency telemetry (5 Hz)
        aegis-vehicle --vehicle-id AMB-002 --vehicle-type ambulance \\
            --telemetry-frequency 5.0
    """
    # Create configuration
    try:
        config = AgentConfig(
            vehicle_id=vehicle_id,
            vehicle_type=VehicleType(vehicle_type.lower()),
            fleet_id=fleet_id,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_password=redis_password,
            telemetry_frequency_hz=telemetry_frequency,
            navigator_provider=navigator_provider.lower(),
            osmnx_place_name=osmnx_place_name,
            osmnx_network_type=osmnx_network_type.lower(),
            initial_latitude=latitude,
            initial_longitude=longitude,
        )
    except Exception as e:
        logger.error("config_validation_failed", error=str(e))
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)

    # Create and run agent
    bus = RedisMessageBus(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password,
        db=config.redis_db,
    )
    agent = VehicleAgent(config, message_bus=bus, clock=RealClock())

    click.echo("🚑 Project AEGIS - Vehicle Agent")
    click.echo(f"   Vehicle ID: {vehicle_id}")
    click.echo(f"   Type: {vehicle_type}")
    click.echo(f"   Fleet: {fleet_id}")
    click.echo(f"   Redis: {redis_host}:{redis_port}")
    click.echo(f"   Frequency: {telemetry_frequency} Hz")
    click.echo(f"   Navigator: {navigator_provider.lower()}")
    click.echo(f"   Location: ({latitude:.4f}, {longitude:.4f})")
    click.echo()
    click.echo("Press Ctrl+C to stop")
    click.echo()

    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        click.echo()
        click.echo(f"✓ {vehicle_id} shutdown complete")
    except Exception as e:
        logger.error("agent_crashed", error=str(e), exc_info=True)
        click.echo(f"❌ Agent crashed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
