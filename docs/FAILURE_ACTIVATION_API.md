# Failure Activation API

**Version:** 2.0.0
**Last Updated:** 2026-03-08

This document describes how to trigger failure scenarios in the current runtime.

## Available Scenarios

From `src/models/enums.py` (`FailureScenario`):

- `ENGINE_OVERHEAT`
- `BATTERY_DEGRADATION`
- `FUEL_LEAK`
- `OIL_PRESSURE_DROP`
- `VIBRATION_ANOMALY`
- `BRAKE_DEGRADATION`

## Programmatic Usage

```python
from src.models.enums import FailureScenario
from src.vehicle_agent.agent import VehicleAgent

agent: VehicleAgent = ...

# Activate
agent.failure_injector.activate_scenario(FailureScenario.ENGINE_OVERHEAT)

# Deactivate
agent.failure_injector.deactivate_scenario(FailureScenario.ENGINE_OVERHEAT)
```

## Notes

- Scenarios are time-progressive based on activation timestamp.
- Multiple active scenarios compound effects.
- Agent tick loop applies failure mutations before alert analysis.
- Critical outcomes can transition vehicle to maintenance mode.

## Testing Reference

See:

- `tests/e2e/test_maintenance_retry.py`
- `src/vehicle_agent/failure_injector.py`
