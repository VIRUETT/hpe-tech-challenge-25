# Testing Guide - Project AEGIS

This guide explains how tests are organized after the architecture refactor.

## Test Structure

```
tests/
├── conftest.py
├── fixtures/
├── unit/                     # Fast isolated tests
├── integration/              # Service-level integration tests
├── bdd/                      # Behavior specs using pytest-bdd
├── e2e/                      # End-to-end async simulation tests
└── features/                 # Gherkin feature files
```

Notable end-to-end suites:

- `tests/e2e/test_dispatch_flow.py`
  - dispatch lifecycle with `FastForwardClock` and `InMemoryMessageBus`
  - validates command flow and telemetry progression without wall-clock waits
- `tests/e2e/test_maintenance_retry.py`
  - validates retry behavior when emergencies wait for available units
  - verifies maintenance/alert-clear interaction with orchestrator retry logic

## 🚀 Quick Start

### Running Tests

```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run all end-to-end tests
uv run pytest tests/e2e/ -v

# Run specific test file
uv run pytest tests/unit/models/test_vehicle.py -v

# Run specific test class
uv run pytest tests/unit/models/test_vehicle.py::TestGeoLocation -v

# Run specific test function
uv run pytest tests/unit/models/test_vehicle.py::TestGeoLocation::test_geolocation_valid_creation -v

# Run tests with coverage
uv run pytest tests/unit/ --cov=src --cov-report=html

# Run only unit tests (using markers)
uv run pytest -m unit

# Run only integration tests
uv run pytest -m integration

# Run BDD tests
uv run pytest tests/bdd/ -v

# Run tests in parallel (faster)
uv run pytest -n auto
```

### Test Markers

Tests are organized using pytest markers:

- `@pytest.mark.unit` - Unit tests (fast, isolated)
- `@pytest.mark.integration` - Integration tests (slower, may need external services)
- `@pytest.mark.slow` - Tests that take a long time
- `@pytest.mark.simulation` - Simulation-specific tests

## 📝 Writing Tests

### Test Naming Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test functions: `test_<what_is_being_tested>`

Example:
```python
# tests/unit/models/test_vehicle.py

@pytest.mark.unit
@pytest.mark.models
class TestVehicleIdentity:
    """Test VehicleIdentity model validation and behavior."""

    def test_vehicle_identity_valid_creation(self) -> None:
        """Test creating a valid VehicleIdentity instance."""
        # Test code here
```

### Using Fixtures

Fixtures provide reusable test data. All model fixtures are defined in `tests/fixtures/model_fixtures.py`.

```python
def test_example(sample_vehicle_identity_data: dict) -> None:
    """Test using a fixture."""
    vehicle = VehicleIdentity(**sample_vehicle_identity_data)
    assert vehicle.vehicle_id == "AMB-001"
```

Available fixtures are defined in `tests/fixtures/` and `tests/conftest.py`.

### Testing Refactored Runtime Components

The runtime now depends on abstractions (`Clock`, `MessageBus`, persistence sinks).
In tests, prefer these patterns:

1. Inject `FastForwardClock` to avoid real-time sleeps.
2. Inject `InMemoryMessageBus` to avoid external Redis dependency.
3. Use noop/in-memory sink implementations for telemetry and alert persistence.
4. Assert behavior (dispatch states, retries, transitions), not internals.

This keeps tests deterministic and fast while preserving realistic async flow.

### Testing Pydantic Models

When testing Pydantic models, focus on:

1. **Valid creation** - Model can be instantiated with valid data
2. **Field validation** - Invalid data raises `ValidationError`
3. **Boundary conditions** - Min/max values, ranges
4. **Default values** - Optional fields have correct defaults
5. **Serialization** - JSON round-trip works correctly

Example:
```python
def test_battery_voltage_bounds(self, sample_telemetry_data: dict) -> None:
    """Test battery_voltage enforces 0 to 30 range."""
    sample_telemetry_data["battery_voltage"] = -0.1
    with pytest.raises(ValidationError):
        VehicleTelemetry(**sample_telemetry_data)

    sample_telemetry_data["battery_voltage"] = 30.1
    with pytest.raises(ValidationError):
        VehicleTelemetry(**sample_telemetry_data)
```

### Testing Enums

Enum tests verify:
- All expected values exist
- Values are correct
- Membership checks work

Example:
```python
def test_vehicle_type_values(self) -> None:
    """Test VehicleType has expected values."""
    assert VehicleType.AMBULANCE.value == "ambulance"
    assert VehicleType.FIRE_TRUCK.value == "fire_truck"
```

## Code Quality Tools

### Running Linters

```bash
# Check code formatting
uv run ruff format --check .

# Auto-fix formatting issues
uv run ruff format .

# Run linter
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Type checking
uv run mypy src/
```

### Pre-commit Hooks

Pre-commit hooks automatically check code quality before commits:

```bash
# Install hooks (one-time setup)
./setup-hooks.sh

# Or manually
pre-commit install
pre-commit install --hook-type commit-msg

# Run manually on all files
pre-commit run --all-files

# Skip hooks (not recommended)
git commit --no-verify
```

Hooks run automatically on:
- **Pre-commit**: Format checking, linting, security scans
- **Commit-msg**: Validate commit message format
- **Pre-push**: Run unit tests before pushing

### CI/CD Pipeline

GitHub Actions automatically runs on:
- Push to `main`, `release`, or `feature/**` branches
- Pull requests to `main` or `release`

Pipeline stages:
1. **Lint**: Code formatting and style checks
2. **Test**: Unit and integration tests
3. **Security**: Dependency vulnerability scanning
4. **Build**: Package build verification

View results at: `.github/workflows/ci.yml`

## Coverage Reports

Coverage reports show which code is tested:

```bash
# Generate HTML coverage report
uv run pytest --cov=src --cov-report=html

# Open report in browser (macOS)
open htmlcov/index.html

# Open report in browser (Linux)
xdg-open htmlcov/index.html
```

**Coverage Goals:**
- Overall: > 80%
- Models: > 95%
- Critical paths: 100%

## Debugging Tests

### Running in Verbose Mode

```bash
# More detailed output
uv run pytest -v

# Show print statements
uv run pytest -s

# Show full traceback
uv run pytest --tb=long

# Drop into debugger on failure
uv run pytest --pdb
```

### Using Pytest Flags

```bash
# Stop after first failure
uv run pytest -x

# Show local variables in traceback
uv run pytest -l

# Rerun only failed tests
uv run pytest --lf

# Run tests that failed last time and new tests
uv run pytest --ff
```

## Best Practices

### DO ✅

- Write descriptive test names that explain what is being tested
- Use fixtures for reusable test data
- Test boundary conditions and edge cases
- Keep tests isolated and independent
- Use appropriate markers (`@pytest.mark.unit`, etc.)
- Test both success and failure paths
- Mock external dependencies in unit tests

### DON'T ❌

- Don't commit commented-out tests
- Don't test implementation details, test behavior
- Don't use `pytest.skip()` without a good reason
- Don't share mutable state between tests
- Don't write tests that depend on execution order
- Don't ignore test warnings

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pydantic Testing Tips](https://docs.pydantic.dev/latest/concepts/testing/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)

## Troubleshooting

### Tests fail with "Module not found"

```bash
# Reinstall dependencies
uv sync --all-extras
```

### Pre-commit hooks failing

```bash
# Update pre-commit hooks
pre-commit autoupdate

# Clear pre-commit cache
pre-commit clean
```

### Coverage not working

```bash
# Install coverage dependencies
uv pip install pytest-cov

# Verify coverage is enabled
uv run pytest --version | grep cov
```

---

**Need help?** Check the main [README.md](../README.md) or [AGENTS.md](../AGENTS.md) for general development guidelines.
