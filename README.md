# Project AEGIS

Digital Twin simulation for emergency fleets (ambulance, fire truck, police) with:

- real-time telemetry streaming,
- orchestrated dispatch,
- predictive maintenance alerts,
- fast API and dashboard integration.

This repository is a POC for the HPE GreenLake Tech Challenge.

## Current Architecture

The codebase was refactored to make behavior clearer and to decouple runtime concerns from infrastructure details.

### Core abstractions (`src/core/`)

- `Clock` (`src/core/time.py`): time control abstraction.
  - `RealClock`: production runtime clock.
  - `FastForwardClock`: deterministic test clock for simulation acceleration.
- `MessageBus` (`src/core/messaging.py`): pub/sub abstraction.
- Persistence contracts (`src/core/persistence.py`): telemetry and alert sinks.

### Infrastructure adapters (`src/infrastructure/`)

- `RedisMessageBus`: Redis-backed pub/sub adapter.
- `InMemoryMessageBus`: in-memory event bus for end-to-end tests.

### Domain services and agents

- Vehicle runtime (`src/vehicle_agent/agent.py`):
  - publishes telemetry and predictive alerts,
  - consumes dispatch/resolve commands,
  - publishes startup registration events (`vehicle.registered`),
  - supports injected `Clock` + `MessageBus`.
- Orchestrator (`src/orchestrator/agent.py`):
  - consumes telemetry, alerts, alerts-cleared, and registration events,
  - runs dispatch and retry logic,
  - supports injected `Clock`, `MessageBus`, and persistence sinks.
- Persistence component (`src/orchestrator/persistence.py`):
  - batched telemetry persistence,
  - alert persistence,
  - separated from orchestrator decision logic.

### Explicit vehicle registration (no ID inference requirement)

At startup, each vehicle emits metadata through:

- channel: `aegis:{fleet_id}:vehicles:register`
- payload: `VehicleRegistrationEvent` (`src/models/events.py`)

The orchestrator registers metadata directly via `FleetService.register_vehicle(...)`.

## Quick Start

Install dependencies:

```bash
uv sync
```

Run orchestrator API:

```bash
uv run aegis-orchestrator
```

Run a single vehicle:

```bash
uv run aegis-vehicle --vehicle-id AMB-001 --vehicle-type ambulance
```

Run fleet simulation:

```bash
uv run aegis-fleet --ambulances 2 --fire-trucks 1 --police 1
```

Run dashboard:

```bash
uv run streamlit run main.py
```

## Testing

Unit tests:

```bash
uv run pytest -m unit
```

Integration/E2E examples:

```bash
uv run pytest tests/e2e/test_dispatch_flow.py
uv run pytest tests/e2e/test_maintenance_retry.py
```

Run all tests:

```bash
uv run pytest
```

## Code Quality

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

## Roadmap Notes

The current architecture is intentionally ready for future extension points:

- route providers (Haversine now, road-constrained engines later),
- alternative message buses,
- accelerated simulation workflows,
- richer event-driven persistence and analytics.

## Documentation Map

- `docs/ARCHITECTURE.md` - Canonical component/event flow overview
- `docs/COMMUNICATION_PROTOCOL.md` - Channel contracts and payload examples
- `docs/DATA_ARCHITECTURE.md` - Runtime data model architecture
- `docs/SIMULATION.md` - Simulation behavior and E2E scenario scope
- `docs/ROADMAP.md` - Current progress and planned evolution
