# Architecture Overview - Project AEGIS

**Version:** 1.0.0
**Last Updated:** 2026-03-08

This document is the canonical high-level view of how AEGIS components interact.

## System Components

- **Vehicle Agent** (`src/vehicle_agent/agent.py`)
  - Generates telemetry
  - Runs local anomaly/failure logic
  - Handles dispatch/resolve commands
- **Orchestrator Agent** (`src/orchestrator/agent.py`)
  - Maintains fleet/emergency state
  - Selects units via dispatch engine
  - Publishes commands and resolves missions
- **Message Bus** (`src/core/messaging.py`)
  - Runtime adapter: `RedisMessageBus`
  - Test adapter: `InMemoryMessageBus`
- **Persistence** (`src/orchestrator/persistence.py`)
  - Telemetry batching and DB writes
  - Alert persistence
- **API + Dashboard** (`src/orchestrator/api.py`, `main.py`)
  - Fleet/emergency/alert read APIs
  - Streamlit visualization

## Core Runtime Contracts

- `Clock` (`src/core/time.py`)
  - `RealClock` for production
  - `FastForwardClock` for deterministic simulation tests
- `MessageBus` (`src/core/messaging.py`)
  - Transport-independent pub/sub contract
- `NavigatorProvider` (`src/vehicle_agent/navigation.py`)
  - `GeometricNavigator` (default)
  - `OSMnxNavigator` (road-constrained)
- `TelemetrySink` and `AlertSink` (`src/core/persistence.py`)
  - Persistence side-effect contracts

## Event Flow Map

### 1) Vehicle startup registration

1. Vehicle starts.
2. Vehicle publishes `VehicleRegistrationEvent` on:
   - `aegis:{fleet_id}:vehicles:register`
3. Orchestrator registers snapshot in fleet service.

### 2) Telemetry ingestion

1. Vehicle publishes `VehicleTelemetry` on:
   - `aegis:{fleet_id}:telemetry:{vehicle_id}`
2. Orchestrator updates in-memory fleet snapshot.
3. Orchestrator enqueues telemetry to persistence sink.
4. Optional: orchestrator broadcasts live update via WebSocket callback.

### 3) Predictive alert processing

1. Vehicle detects anomaly and publishes `PredictiveAlert` on:
   - `aegis:{fleet_id}:alerts:{vehicle_id}`
2. Orchestrator marks vehicle with active alert.
3. Orchestrator persists alert asynchronously.

### 4) Dispatch lifecycle

1. Emergency enters orchestrator (`aegis:emergencies:new` or API).
2. Orchestrator selects nearest available units.
3. Orchestrator sends command per unit:
   - `aegis:{fleet_id}:commands:{vehicle_id}` (`command=dispatch`)
4. Vehicle transitions to `EN_ROUTE`, then `ON_SCENE` on arrival.

### 5) Resolve lifecycle

1. Emergency is resolved by orchestrator.
2. Orchestrator publishes:
   - `aegis:dispatch:{emergency_id}:resolved` (`command=resolve`)
3. Assigned vehicles transition back to `IDLE`.

### 6) Maintenance + retry flow

1. Vehicle enters maintenance and later publishes clear event:
   - `aegis:{fleet_id}:alerts_cleared:{vehicle_id}`
2. Orchestrator clears active-alert state.
3. Orchestrator retries emergencies stuck in `DISPATCHING`.

## Why this architecture

- Keeps latency-sensitive dispatch loop simple and explicit.
- Separates transport/time/persistence concerns for readability and testability.
- Enables deterministic end-to-end tests without Redis.
- Preserves extension points for routing engines and background workers.

## Testability model

- End-to-end tests inject:
  - `InMemoryMessageBus`
  - `FastForwardClock`
- This allows accelerated simulation and deterministic async behavior.

Reference suites:

- `tests/e2e/test_dispatch_flow.py`
- `tests/e2e/test_maintenance_retry.py`

## Related Docs

- `docs/COMMUNICATION_PROTOCOL.md`
- `docs/DATA_ARCHITECTURE.md`
- `docs/SIMULATION.md`
- `docs/ROADMAP.md`
