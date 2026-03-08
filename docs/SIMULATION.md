# Simulation Guide - Project AEGIS

**Version:** 2.0.0
**Scope:** Current implemented behavior and testable scenarios
**Last Updated:** 2026-03-08

## Overview

AEGIS simulation currently focuses on deterministic, testable fleet behavior:

- synthetic telemetry generation,
- dispatch/resolve lifecycle,
- predictive maintenance signal flow,
- bounded geographic movement in San Francisco area.

## Movement Model (Current)

The current movement engine is geometric, not road-network-based:

- straight-line navigation (haversine/bearing-based tick movement),
- SF boundary clamping via values in `src/vehicle_agent/config.py`,
- EN_ROUTE target-following with ON_SCENE transition when arrival condition is met.

This is intentionally lightweight for POC reliability and fast execution.

## Navigator Providers

Movement is now pluggable through a `NavigatorProvider` (`src/vehicle_agent/navigation.py`).

- `geometric` (default): current straight-line behavior with SF boundary clamping.
- `osmnx`: road-constrained routing via OSMnx + NetworkX shortest path.

When `osmnx` cannot load graph data or compute a route, it gracefully falls
back to geometric movement so simulation does not fail hard.

CLI examples:

```bash
uv run aegis-vehicle --vehicle-id AMB-001 --vehicle-type ambulance --navigator-provider osmnx
uv run aegis-fleet --ambulances 3 --fire-trucks 1 --navigator-provider osmnx
```

Default OSM place is San Francisco:

- `osmnx_place_name = "San Francisco, California, USA"`
- `osmnx_network_type = "drive"`

## Failure and Maintenance Behavior

Failure injection is implemented in `src/vehicle_agent/failure_injector.py`.

Supported scenarios include:

- `ENGINE_OVERHEAT`
- `BATTERY_DEGRADATION`
- `FUEL_LEAK`
- `OIL_PRESSURE_DROP`
- `VIBRATION_ANOMALY`
- `BRAKE_DEGRADATION`

Runtime behavior:

1. Scenario activated in agent failure injector.
2. Telemetry values are progressively modified over time.
3. Alert logic may emit warning/critical events.
4. Critical conditions can trigger maintenance mode.
5. Maintenance completion publishes `alerts_cleared` and vehicle returns to service.

## Simulation Time Modes

### Real-time mode

- `RealClock` in production execution.
- Tick pacing uses real async sleeps.

### Fast-forward mode (tests)

- `FastForwardClock` in E2E tests.
- Time advances manually for deterministic progression.
- Enables multi-minute scenarios in seconds.

## End-to-End Scenarios Implemented

- `tests/e2e/test_dispatch_flow.py`
  - vehicle registration + dispatch + on-scene + resolve lifecycle
  - fast-forward telemetry progression
- `tests/e2e/test_maintenance_retry.py`
  - waiting emergency in `dispatching`
  - maintenance/clear event triggers dispatch retry

## Operational Limits (Current)

- No road-constrained routing yet.
- No traffic-aware ETA engine.
- No distributed worker queue in control loop.

These are valid future extensions and do not block current POC behavior.

## Suggested Next Simulation Extensions

1. Introduce `NavigationProvider` abstraction (current geometric navigator as default).
2. Add road-constrained implementation (OSMnx first, Valhalla optional later).
3. Add hotspot-weighted emergency generation and point snapping to valid map nodes.
