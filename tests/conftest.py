"""Shared fixtures and helpers for lcn2mqtt tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypck import lcn_defs
from pypck.device import Serials
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device

_FIXTURE_YAML = Path(__file__).parent / "fixtures" / "conf.yaml"


def make_config() -> AppConfig:
    """Build an AppConfig from the test fixture YAML."""
    return AppConfig(yaml_file=_FIXTURE_YAML)


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
    bridge._pchk.physical_to_logical = lambda addr: addr
    bridge._mqtt = AsyncMock()
    bridge._discovery = None
    return bridge


@pytest.fixture
def mock_device_conn() -> MagicMock:
    """Return a mock device connection that reports a valid serial and a name."""
    conn = MagicMock()
    conn.serials_known = AsyncMock()
    conn.serials = Serials(
        hardware_serial=0x1A20A1234,
        manu=0x1,
        software_serial=0x190B11,
        hardware_type=lcn_defs.HardwareType.SH_PLUS,
    )
    conn.request_name = AsyncMock(return_value="TestModule")
    return conn


@pytest.fixture
def module() -> Device:
    """Return a fresh Module instance with no device connection."""
    return Device(address=LcnAddr(0, 7, False))


@pytest.fixture
def module_with_conn(module: Device) -> Device:
    """Return module with a mock async device connection (new firmware)."""
    conn = AsyncMock()
    conn.serials.software_serial = 0x180000  # > 0x170206 → new firmware
    module.device_connection = conn
    return module
