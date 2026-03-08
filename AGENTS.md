# AGENTS.md - Project AEGIS

This file is for agentic coding assistants operating in this repository.

## Project Snapshot

- Project: HPE GreenLake Tech Challenge - Project AEGIS
- Domain: digital twin emergency fleet (ambulance, fire, police)
- Language/runtime: Python 3.13
- Package/environment manager: `uv`
- Source tree: `src/`
- Test tree: `tests/` (`unit/`, `integration/`, `bdd/`, `e2e/`, `features/`)

## Repository Layout

- `src/core/`: abstractions (`Clock`, messaging contracts, persistence contracts)
- `src/infrastructure/`: implementations (`RedisMessageBus`, `InMemoryMessageBus`)
- `src/vehicle_agent/`: vehicle behavior and telemetry runtime
- `src/orchestrator/`: dispatch coordination and emergency workflow
- `src/models/`: Pydantic models and event payloads
- `src/storage/`: DB config, models, repositories
- `src/ml/`: prediction/training components
- `src/scripts/`: CLI entrypoints (`aegis-vehicle`, `aegis-orchestrator`, `aegis-fleet`)

## Build And Setup Commands

```bash
# Install dependencies
uv sync

# CI-like install (all extras)
uv sync --all-extras

# Runtime-only install
uv sync --no-dev

# Build distribution artifacts
uv build
```

## Test Commands (Pytest)

Prefer the smallest useful scope first.

```bash
# Single test function (preferred for quick iteration)
uv run pytest tests/unit/models/test_models.py::TestVehicleIdentity::test_vehicle_identity_valid_creation -v

# Single test class
uv run pytest tests/unit/vehicle_agent/test_agent.py::TestVehicleAgent -v

# Single test file
uv run pytest tests/unit/orchestrator/test_dispatch_engine.py -v

# Marker-based runs
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m simulation

# BDD / E2E
uv run pytest tests/bdd/ -v
uv run pytest tests/e2e/ -v

# Parallel
uv run pytest -n auto

# Full suite
uv run pytest
```

Useful debug flags:

```bash
uv run pytest -x -v
uv run pytest --lf
uv run pytest -s --tb=long
uv run pytest --pdb
```

## Lint, Format, Type, Security, Docs

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run ruff check --fix .
uv run mypy src/
uv run bandit -r src/
uv run pydocstyle src/
pre-commit run --all-files
```

Pre-commit hooks available in this repo include file hygiene checks, Ruff lint/format,
mypy, Bandit, pydocstyle, pyupgrade, and commit message validation.

## Code Style And Implementation Guidelines

- Line length: 100 characters (`ruff`)
- Python target: 3.13 (`ruff` + `mypy`)
- Type hints: required for all functions and methods (`mypy` strict options)
- Docstrings: Google style (`pydocstyle`)
- Data validation: use Pydantic models for external I/O and event payloads
- Logging: use `structlog`; avoid `print()` in production paths
- Async: use `async`/`await` for I/O, messaging, and background workers
- Secrets/config: never hardcode; load from env/config

### Imports

Use three groups separated by blank lines:

1. Standard library
2. Third-party packages
3. Local `src.*` imports

Ruff import sorting is enabled (`I` rules).

### Naming

- Classes and enums: `PascalCase`
- Functions, methods, variables, modules: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private/internal members: leading underscore (`_internal_name`)
- Tests:
  - files: `test_<module>.py`
  - classes: `Test<ClassName>`
  - functions: `test_<behavior>_<condition>_<expected>`

### Error Handling

- Use specific exceptions; avoid bare `except:`
- Validate early and fail fast (prefer Pydantic for schema-level validation)
- In async tasks, log structured context (IDs, channels, payload metadata)
- Re-raise only when callers have meaningful recovery/handling logic

## Architecture Notes For Agents

- Follow pub/sub channel contracts; keep transport concerns out of domain services
- Keep business logic in `fleet_service` and `emergency_service`
- Prefer dependency injection via abstractions (`Clock`, `MessageBus`, sinks)
- In tests, favor deterministic dependencies (`FastForwardClock`, `InMemoryMessageBus`)
- Assert behavior and outcomes, not internal implementation details

## Cursor And Copilot Rules

Detected Cursor rules:

- `.cursor/rules/tessl__rule__tessl__cli-setup__query_library_docs.mdc`

Cursor rule requirement:

- Before most code tasks (especially debugging, edits, architecture questions), call the Tessl documentation tool `query_library_docs` with relevant terms.
- If lookup fails or is not useful, continue normally.

Detected Copilot instructions:

- No `.github/copilot-instructions.md` file found in this repository.

# Agent Rules <!-- tessl-managed -->

@.tessl/RULES.md follow the [instructions](.tessl/RULES.md)
