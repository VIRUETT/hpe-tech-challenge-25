"""
CLI entry point for starting the AEGIS Orchestrator.

Provides the 'aegis-orchestrator' command which starts the FastAPI server
and the Redis subscriber loop concurrently.
"""

import sys

import click
import structlog
import uvicorn

from src.core.time import RealClock
from src.infrastructure.redis_bus import RedisMessageBus
from src.orchestrator.agent import OrchestratorAgent
from src.orchestrator.api import create_app

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
    "--host",
    default="0.0.0.0",
    show_default=True,
    help="API server bind host",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    show_default=True,
    help="API server port",
)
@click.option(
    "--redis-host",
    default="localhost",
    show_default=True,
    help="Redis server hostname",
)
@click.option(
    "--redis-port",
    default=6379,
    type=int,
    show_default=True,
    help="Redis server port",
)
@click.option(
    "--redis-password",
    default=None,
    help="Redis password (optional)",
)
@click.option(
    "--fleet-id",
    default="fleet01",
    show_default=True,
    help="Fleet identifier",
)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable auto-reload for development",
)
def main(
    host: str,
    port: int,
    redis_host: str,
    redis_port: int,
    redis_password: str | None,
    fleet_id: str,
    reload: bool,
) -> None:
    """Start the AEGIS Orchestrator API server.

    Launches the FastAPI server with the Redis subscriber loop.
    The orchestrator listens to all vehicle telemetry, maintains fleet state,
    and processes emergencies via POST /emergencies.

    Examples:

        \\b
        # Start with defaults (localhost Redis, port 8000)
        aegis-orchestrator

        \\b
        # Custom Redis and port
        aegis-orchestrator --redis-host redis.local --port 9000

        \\b
        # Development mode with auto-reload
        aegis-orchestrator --reload
    """
    click.echo("Project AEGIS - Orchestrator")
    click.echo(f"   API: http://{host}:{port}")
    click.echo(f"   Docs: http://{host}:{port}/docs")
    click.echo(f"   Redis: {redis_host}:{redis_port}")
    click.echo(f"   Fleet: {fleet_id}")
    click.echo()
    click.echo("Press Ctrl+C to stop")
    click.echo()

    try:
        orchestrator = OrchestratorAgent(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_password=redis_password,
            redis_db=0,
            fleet_id=fleet_id,
            message_bus=RedisMessageBus(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                db=0,
            ),
            clock=RealClock(),
        )

        app = create_app(orchestrator)

        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )

    except KeyboardInterrupt:
        click.echo()
        click.echo("Orchestrator shutdown complete")
    except Exception as e:
        logger.error("orchestrator_crashed", error=str(e), exc_info=True)
        click.echo(f"Orchestrator crashed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
