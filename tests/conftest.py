"""
Pytest configuration and shared fixtures for RDR2 Mobile Controller tests.
"""

import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from starlette.testclient import TestClient

from gamepad.mock_adapter import MockGamepadAdapter
from server import create_app


@pytest.fixture
def mock_adapter():
    """Provides an initialized MockGamepadAdapter for isolated unit testing."""
    adapter = MockGamepadAdapter()
    adapter.initialize()
    return adapter


@pytest.fixture
def fixed_pin():
    return "654321"


@pytest.fixture
def test_app(mock_adapter, fixed_pin):
    """Provides a FastAPI app instance wired with MockGamepadAdapter and a fixed PIN."""
    return create_app(adapter=mock_adapter, pairing_pin=fixed_pin)


@pytest.fixture
def client(test_app):
    """Provides a synchronous HTTP & WebSocket TestClient."""
    with TestClient(test_app) as c:
        yield c
