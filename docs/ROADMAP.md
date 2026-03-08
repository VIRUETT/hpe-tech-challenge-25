# Project AEGIS Roadmap

**Version:** 2.0.0
**Last Updated:** 2026-03-08

## Completed Baseline

- Core abstractions introduced (`Clock`, `MessageBus`, persistence sinks).
- Redis and in-memory bus adapters implemented.
- Vehicle/orchestrator refactored to dependency-injected runtime contracts.
- Explicit vehicle registration event flow implemented.
- Orchestrator persistence decoupled via persister components.
- UTC timestamp consistency improved in core models.
- E2E fast-forward suites added for dispatch and maintenance retry.

## Near-Term Priorities

### 1) Navigation abstraction and map realism

- Introduce `NavigationProvider` contract.
- Keep current geometric strategy as default implementation.
- Add optional road-constrained implementation (OSMnx first).
- Evaluate Valhalla integration for ETA/route quality if needed.

### 2) Stronger scenario coverage

- Add E2E for multi-unit dispatch edge cases.
- Add E2E for high-frequency alert bursts and backpressure.
- Add E2E for stale emergency sweeper and timeout policies.

### 3) Observability and ops polish

- Add metrics for dispatch latency, queue depth, and persistence lag.
- Add health endpoints and clearer runtime diagnostics.

## Medium-Term

- Introduce richer event taxonomy for domain events.
- Add replay-friendly event capture for simulation analysis.
- Evaluate background task queue for non-real-time workloads only.

## Task Queue Position (Taskiq)

Taskiq is optional and should not replace the real-time control loop.

- Use current message bus for dispatch/telemetry/control events.
- Consider Taskiq later for heavy async jobs:
  - offline analytics,
  - enrichment pipelines,
  - long-running route preprocessing,
  - scheduled maintenance workflows.

This keeps latency-sensitive orchestration simple while still allowing scalable async job execution where it helps.
