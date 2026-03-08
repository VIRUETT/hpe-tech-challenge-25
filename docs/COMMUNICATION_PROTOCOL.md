# Communication Protocol - Project AEGIS

**Version:** 2.0.0
**Protocol:** Redis Pub/Sub via `MessageBus` abstraction
**Message Format:** JSON (Pydantic models)
**Last Updated:** 2026-03-08

## Overview

AEGIS uses event-driven communication across vehicle agents and the orchestrator.

- Production transport: Redis pub/sub (`RedisMessageBus`)
- Test transport: in-memory bus (`InMemoryMessageBus`)
- Contract surface: `src/core/messaging.py`

The protocol is intentionally simple and channel-oriented.

## Channel Patterns in Use

### Vehicle -> Orchestrator

- `aegis:{fleet_id}:vehicles:register`
  - Startup metadata registration (`VehicleRegistrationEvent`)
- `aegis:{fleet_id}:telemetry:{vehicle_id}`
  - Telemetry stream (`VehicleTelemetry`)
- `aegis:{fleet_id}:alerts:{vehicle_id}`
  - Predictive alert events (`PredictiveAlert`)
- `aegis:{fleet_id}:alerts_cleared:{vehicle_id}`
  - Maintenance clear notification (JSON payload)

### Orchestrator -> Vehicle

- `aegis:{fleet_id}:commands:{vehicle_id}`
  - Direct dispatch commands
- `aegis:dispatch:{emergency_id}:resolved`
  - Resolution broadcast to release assigned units

### Orchestrator Subscriptions

The orchestrator subscribes with patterns:

- `aegis:*:vehicles:register`
- `aegis:*:telemetry:*`
- `aegis:*:alerts:*`
- `aegis:*:alerts_cleared:*`
- `aegis:emergencies:new`

## Message Payloads

### 1) Vehicle Registration Event

Channel:

`aegis:fleet01:vehicles:register`

Payload model:

- `src/models/events.py` -> `VehicleRegistrationEvent`
- nested `src/models/vehicle.py` -> `VehicleRegistration`

Example:

```json
{
  "event": "vehicle.registered",
  "payload": {
    "vehicle_id": "AMB-001",
    "vehicle_type": "ambulance",
    "fleet_id": "fleet01",
    "operational_status": "idle",
    "timestamp": "2026-03-08T00:00:00Z"
  }
}
```

### 2) Telemetry Event

Channel:

`aegis:fleet01:telemetry:AMB-001`

Payload model:

- `src/models/telemetry.py` -> `VehicleTelemetry`

Example:

```json
{
  "vehicle_id": "AMB-001",
  "vehicle_type": "ambulance",
  "timestamp": "2026-03-08T00:00:01Z",
  "latitude": 37.7749,
  "longitude": -122.4194,
  "speed_kmh": 40.0,
  "odometer_km": 1234.5,
  "engine_temp_celsius": 89.2,
  "battery_voltage": 13.7,
  "fuel_level_percent": 74.5,
  "operational_status": "en_route"
}
```

### 3) Alert Event

Channel:

`aegis:fleet01:alerts:AMB-001`

Payload model:

- `src/models/alerts.py` -> `PredictiveAlert`

### 4) Dispatch Command

Channel:

`aegis:fleet01:commands:AMB-001`

Example:

```json
{
  "command": "dispatch",
  "emergency_id": "2da5c2b7-7e34-4ee4-a020-ff33e274f530",
  "emergency_type": "medical",
  "location": {
    "latitude": 37.779,
    "longitude": -122.41
  },
  "dispatch_id": "f2f09bd6-54e6-4ca0-8d8f-3d645fbcd167"
}
```

### 5) Resolve Broadcast

Channel:

`aegis:dispatch:{emergency_id}:resolved`

Example:

```json
{
  "command": "resolve",
  "emergency_id": "2da5c2b7-7e34-4ee4-a020-ff33e274f530",
  "released_vehicles": ["AMB-001", "FIRE-001"]
}
```

## Operational Rules

- Vehicle startup publishes registration before steady-state telemetry.
- Telemetry can also carry `vehicle_type`; orchestrator uses explicit metadata and keeps snapshot updated.
- Resolution messages must include `"command": "resolve"` so vehicles apply state transition.
- All timestamps are UTC-aware ISO 8601.

## Why this protocol shape

- Keeps control loop low latency and easy to inspect.
- Works with both Redis and in-memory runtime for deterministic E2E tests.
- Separates real-time control from storage concerns (persistence handled by sinks).

## Future evolution

- Keep this channel contract stable while adding route/navigation providers.
- If background job workload grows, add a task queue for non-real-time work only.
- MQTT/Kafka migration should preserve event payload schemas where possible.
