"""Shared fixtures and helpers for lcn2mqtt tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.models.config import AppConfig

_FIXTURE_YAML = Path(__file__).parent / "fixtures" / "configuration.yaml"


def make_config() -> AppConfig:
    """Build an AppConfig from the test fixture YAML."""
    return AppConfig(_FIXTURE_YAML)


@pytest.fixture
def config() -> AppConfig:
    """Minimal AppConfig fixture."""
    return make_config()


@pytest.fixture
def bridge(config: AppConfig) -> Bridge:
    """Bridge fixture backed by a minimal config."""
    return Bridge(config)


@pytest.fixture
def bridge_with_pchk(bridge: Bridge) -> Bridge:
    """Bridge fixture with mocked PCHK, MQTT and no discovery."""
    bridge._pchk = MagicMock()
    bridge._mqtt = AsyncMock()
    bridge._discovery = None
    return bridge


@pytest.fixture
def mock_device_conn() -> MagicMock:
    """A mock device connection that reports a valid serial and a name."""
    conn = MagicMock()
    conn.serials_known = AsyncMock()
    conn.serials.hardware_serial = 1
    conn.request_name = AsyncMock(return_value="TestModule")
    return conn
