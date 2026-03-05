# Agent Development Guide - Project AEGIS

**Project:** HPE GreenLake Tech Challenge - Digital Twin
**Language:** Python 3.13 | **Manager:** `uv` | **Status:** POC

This guide provides crucial context, commands, and rules for AI coding agents operating in this repository.

## 🛠️ Development Commands

### Environment & Execution

```bash
uv sync                           # Install all dependencies (including dev)
uv sync --no-dev                  # Production dependencies only
uv run python main.py             # Main entry point
uv run aegis-vehicle              # Vehicle simulation
uv run aegis-orchestrator         # Central coordinator
```

### Testing (Pytest)

Agents must verify their work. Running a **single test** for targeted validation is highly recommended:

```bash
# Running a single test (Recommended for rapid iteration):
uv run pytest tests/unit/models/test_vehicle.py::TestGeoLocation::test_geolocation_valid_creation

# Other test commands:
uv run pytest                                     # Run all tests
uv run pytest tests/unit/models/test_vehicle.py   # Run specific file
uv run pytest -m unit                             # Run only unit tests
uv run pytest -m integration                      # Run integration tests
uv run pytest --cov=src --cov-report=term-missing # Check missing coverage
```

### Linting, Formatting & Type Checking

```bash
uv run ruff format .              # Format code (auto-fix)
uv run ruff check --fix .         # Lint and fix auto-fixable issues
uv run mypy src/                  # Type checking (strict mode)
uv run bandit -r src/             # Security scanning
uv run pydocstyle src/            # Docstring validation (Google style)
pre-commit run --all-files        # Run all pre-commit hooks
```

## 📁 Project Structure

- `src/`: Source code modules
  - `models/`: Pydantic data models (validation & serialization)
  - `vehicle_agent/`: Digital twin agents
  - `orchestrator/`: Central coordinator
  - `ml/` & `storage/`: Machine learning & persistence
- `tests/`: Contains `unit/`, `integration/`, and `fixtures/`

## 🎨 Code Style Guidelines

- **Line Length:** 100 characters max.
- **Type Hints:** Required for ALL functions/methods (`mypy` strict mode is enforced).
- **Docstrings:** Google Style is mandatory for classes and public methods.
- **Naming Conventions:**
  - Classes: `PascalCase` (e.g., `VehicleDigitalTwin`)
  - Functions/Variables: `snake_case` (e.g., `process_telemetry`)
  - Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
  - Private Members: `_leading_underscore` (e.g., `_validate_data`)
- **Async/Await:** Used extensively for network, pub/sub (Redis/MQTT), and I/O.
- **Error Handling:** Use specific, targeted exceptions. NEVER use a bare `except:`.

### Imports Structure (PEP 8)

Always group imports logically, separated by blank lines:

```python
# 1. Standard library
import os
from typing import Any, Dict

# 2. Third-party
import pytest
from pydantic import BaseModel

# 3. Local application
from src.models.vehicle import VehicleIdentity
```

## ✅ Testing Standards

- **Test Naming:**
  - Files: `test_<module>.py`
  - Classes: `Test<ClassName>`
  - Functions: `test_<what>_<condition>_<expected>` (e.g., `test_geolocation_latitude_bounds`)
- **Mocking:** Use `unittest.mock.AsyncMock` when patching async operations like `redis_client.publish`.
- **Fixtures:** Centralize common test data in `conftest.py` or within `tests/fixtures/`.

## 🔒 Architecture & Best Practices

1. **Message Broker Pattern:** Vehicles publish telemetry and subscribe to alerts asynchronously.
2. **Pydantic Validation:** Always use Pydantic models to validate system inputs/outputs.
3. **Structured Logging:** Use `structlog` for JSON logs instead of `print()`.
4. **Timeouts:** Ensure all async I/O operations and network requests utilize appropriate timeouts.
5. **Secrets:** Never hardcode secrets. Read them from the environment (e.g., via a `.env` file).

# Agent Rules <!-- tessl-managed -->

@.tessl/RULES.md follow the [instructions](.tessl/RULES.md)
