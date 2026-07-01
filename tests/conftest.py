"""Shared fixtures and helpers for lcn2mqtt tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.module import Module

_FIXTURE_YAML = Path(__file__).parent / "fixtures" / "conf.yaml"


def make_config() -> AppConfig:
    """Build an AppConfig from the test fixture YAML."""
    return AppConfig(_FIXTURE_YAML)


@pytest.fixture
def config() -> AppConfig:
    """Minimal AppConfig fixture."""
    return make_config()


@pytest.fixture
def bridge(config: AppConfig) -> Bridge:
    """Return a bridge backed by a minimal config."""
    return Bridge(config)


@pytest.fixture
def bridge_with_pchk(bridge: Bridge) -> Bridge:
    """Return a bridge with mocked PCHK, MQTT and no discovery."""
    bridge._pchk = MagicMock()
    bridge._mqtt = AsyncMock()
    bridge._discovery = None
    return bridge


@pytest.fixture
def mock_device_conn() -> MagicMock:
    """Return a mock device connection that reports a valid serial and a name."""
    conn = MagicMock()
    conn.serials_known = AsyncMock()
    conn.serials.hardware_serial = 1
    conn.request_name = AsyncMock(return_value="TestModule")
    return conn


@pytest.fixture
def module() -> Module:
    """Return a fresh Module instance with no device connection."""
    return Module(address=LcnAddr(0, 7, False))


@pytest.fixture
def module_with_conn(module: Module) -> Module:
    """Return module with a mock async device connection (new firmware)."""
    conn = AsyncMock()
    conn.serials.software_serial = 0x180000  # > 0x170206 → new firmware
    module._device_connection = conn
    return module
