"""
Pytest configuration and shared fixtures for Project AEGIS tests.

This module is automatically loaded by pytest and provides global
test configuration and fixtures available to all test modules.
"""

import sys
from pathlib import Path

import pytest

# Add src directory to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Import all fixtures from fixture modules
pytest_plugins = [
    "fixtures.model_fixtures",
]


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests for individual components")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Tests that take a long time to run")
    config.addinivalue_line("markers", "simulation: Simulation-specific tests")
    config.addinivalue_line("markers", "models: Model validation and serialization tests")


@pytest.fixture(autouse=True)
def reset_environment() -> None:
    """Reset environment variables before each test."""
    # This ensures tests are isolated and don't affect each other
    pass


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client for testing."""
    from unittest.mock import AsyncMock, MagicMock

    mock = MagicMock()
    mock.publish = AsyncMock()
    mock.get = AsyncMock()
    mock.set = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    return mock
