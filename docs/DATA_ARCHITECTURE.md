# Data Architecture - Project AEGIS

**Version:** 2.0.0
**Status:** Implemented (POC with refactored boundaries)
**Last Updated:** 2026-03-08

## Overview

AEGIS models emergency fleets as autonomous vehicle agents coordinated by a central orchestrator.
The architecture now separates:

- runtime control (agents + orchestrator),
- transport (message bus),
- time source (clock abstraction),
- persistence side effects (sinks/persisters).

## Code-Level Architecture

### Core Contracts (`src/core/`)

- `time.py`
  - `Clock`
  - `RealClock`
  - `FastForwardClock` (test acceleration)
- `messaging.py`
  - `MessageBus`
  - `BusMessage`
- `persistence.py`
  - `TelemetrySink`
  - `AlertSink`

### Infrastructure (`src/infrastructure/`)

- `redis_bus.py` -> production transport
- `in_memory_bus.py` -> deterministic E2E transport

### Domain + Runtime

- `src/vehicle_agent/agent.py`
  - emits registration, telemetry, alerts
  - consumes dispatch/resolve commands
- `src/orchestrator/agent.py`
  - consumes registration, telemetry, alerts, clear events
  - dispatch and retry orchestration
- `src/orchestrator/fleet_service.py`
  - fleet snapshot management and registration handling
- `src/orchestrator/emergency_service.py`
  - emergency lifecycle and dispatch coordination
- `src/orchestrator/persistence.py`
  - DB telemetry batching + alert persistence

## Canonical Data Models

### Vehicle and Location

- `src/models/vehicle.py`
  - `Vehicle`
  - `Location`
  - `VehicleRegistration`

### Telemetry

- `src/models/telemetry.py`
  - `VehicleTelemetry`
  - includes `vehicle_type` for explicit metadata propagation

### Alerts

- `src/models/alerts.py`
  - `PredictiveAlert`

### Emergency and Dispatch

- `src/models/emergency.py`
  - `Emergency`, `UnitsRequired`, enums
- `src/models/dispatch.py`
  - `Dispatch`, `DispatchedUnit`, `VehicleStatusSnapshot`

### Events

- `src/models/events.py`
  - `VehicleRegistrationEvent`

## State and Data Flow

1. Vehicle starts and publishes `VehicleRegistrationEvent`.
2. Orchestrator registers/updates snapshot via `FleetService.register_vehicle(...)`.
3. Vehicle streams `VehicleTelemetry`.
4. Orchestrator updates fleet state and enqueues persistence via `TelemetrySink`.
5. Vehicle emits `PredictiveAlert` when anomaly logic triggers.
6. Orchestrator updates active alert state and persists via `AlertSink`.
7. Dispatch commands and resolve broadcasts update vehicle operational status.

## Persistence Strategy

- Online source of truth for runtime decisions: in-memory fleet/emergency state.
- Persistence side effects:
  - telemetry batched by `DatabaseTelemetryPersister`
  - alerts persisted by `DatabaseAlertPersister`
- DB writes are asynchronous relative to control-loop behavior.

## Time and Determinism

- Runtime uses `RealClock`.
- E2E tests use `FastForwardClock` to advance simulation without wall-clock delays.
- Timestamp defaults in core models are UTC-aware.

## Notes on Legacy Concepts

- Earlier docs referenced a large envelope format and many unimplemented telemetry fields.
- Current implementation uses direct model JSON payloads over channels.
- The documented architecture reflects actual code in `src/` as of this version.
