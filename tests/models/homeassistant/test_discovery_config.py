"""Tests for HomeAssistantModuleDiscoveryConfig."""

from __future__ import annotations

from typing import Any

import pytest
from pypck.lcn_addr import LcnAddr
from syrupy.assertion import SnapshotAssertion

from lcn2mqtt.models.homeassistant.components import (
    BinarySensorComponent,
    CoverComponent,
    LightComponent,
    NumberComponent,
    SelectComponent,
    SwitchComponent,
)
from lcn2mqtt.models.homeassistant.discovery import (
    STANDARD_COMPONENTS,
    HomeAssistantModuleDiscoveryConfig,
)

ADDR = LcnAddr(0, 7, False)
BASE_TOPIC = "lcntest"
PREFIX = f"{BASE_TOPIC}/module/0/7"


def make_config(
    addr: LcnAddr = ADDR, **kwargs: Any
) -> HomeAssistantModuleDiscoveryConfig:
    """Return a HomeAssistantModuleDiscoveryConfig with the given address and kwargs."""
    return HomeAssistantModuleDiscoveryConfig(address=addr, **kwargs)


class TestDefaultComponents:
    """Default config creates exactly the standard components."""

    def test_standard_components_created(self) -> None:
        """Standard components are created."""
        cfg = make_config()
        assert set(cfg.components.keys()) == set(STANDARD_COMPONENTS)

    def test_no_extra_components_by_default(self) -> None:
        """Non-default included components are not present by default."""
        cfg = make_config()
        not_standard = set(cfg.components.keys()) - set(STANDARD_COMPONENTS)
        assert len(not_standard) == 0


class TestIncludeExclude:
    """Tests for include/exclude filtering."""

    def test_explicit_include_limits_components(self) -> None:
        """Only included components are created."""
        cfg = make_config(include=["relay1", "relay2"])
        assert set(cfg.switches.keys()) == {"relay1", "relay2"}
        assert not cfg.lights

    def test_exclude_removes_component(self) -> None:
        """Excluded component is not present in the result."""
        cfg = make_config(exclude=["relay1"])
        assert "relay1" not in cfg.switches

    def test_exclude_does_not_affect_others(self) -> None:
        """Components not in exclude are still present."""
        cfg = make_config(exclude=["relay1"])
        for i in range(2, 9):
            assert f"relay{i}" in cfg.switches

    def test_wildcard_include_expands(self) -> None:
        """Wildcard pattern in include expands to all matching components."""
        cfg = make_config(include=["binsensor*"])
        assert len(cfg.binary_sensors) == 8  # 8 binary sensor ports

    def test_wildcard_exclude(self) -> None:
        """Wildcard pattern in exclude removes all matching components."""
        cfg = make_config(exclude=["relay*"])
        assert not cfg.switches

    def test_include_binsensors_creates_binary_sensors(self) -> None:
        """Including binsensor ports creates BinarySensorComponent instances."""
        cfg = make_config(include=["binsensor1"])
        assert isinstance(cfg.binary_sensors["binsensor1"], BinarySensorComponent)

    def test_include_relays_creates_switches(self) -> None:
        """Including relay ports creates SwitchComponent instances."""
        cfg = make_config(include=["relay1"])
        assert isinstance(cfg.switches["relay1"], SwitchComponent)

    def test_include_outputs_creates_lights(self) -> None:
        """Including output ports creates LightComponent instances."""
        cfg = make_config(include=["output1"])
        assert isinstance(cfg.lights["output1"], LightComponent)

    def test_include_leds_creates_selects(self) -> None:
        """Including LED ports creates SelectComponent instances."""
        cfg = make_config(include=["led1"])
        assert isinstance(cfg.selects["led1"], SelectComponent)

    def test_include_motors_creates_covers(self) -> None:
        """Including motor ports creates CoverComponent instances."""
        cfg = make_config(include=["motor1"])
        assert isinstance(cfg.covers["motor1"], CoverComponent)

    def test_include_vars_creates_numbers(self) -> None:
        """Including variable ports creates NumberComponent instances."""
        cfg = make_config(include=["var1"])
        assert isinstance(cfg.numbers["var1"], NumberComponent)

    def test_empty_include_creates_no_components(self) -> None:
        """An explicitly empty include results in no components."""
        cfg = make_config(include=[])
        assert not cfg.components


class TestManualComponents:
    """Tests for manually defined components in config."""

    def test_manual_light(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined light."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            lights={"output1": {"target": "output1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.lights["output1"] == snapshot

    def test_manual_switch(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined switch."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            switches={"relay1": {"target": "relay1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.switches["relay1"] == snapshot

    def test_manual_climate(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined climate component."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            climates={
                "climate1": {
                    "temperature": "R1VARSETPOINT",
                    "current_temperature": "VAR1",
                }
            },
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.climates["climate1"] == snapshot

    def test_manual_binary_sensor(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined binary sensor."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            binary_sensors={"binsensor1": {"source": "binsensor1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.binary_sensors["binsensor1"] == snapshot

    def test_manual_number(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined number component."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            numbers={"var1": {"target": "var1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.numbers["var1"] == snapshot

    def test_manual_select(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined select component."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            selects={"led1": {"target": "led1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.selects["led1"] == snapshot

    def test_manual_cover(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined cover component."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            covers={"motor1": {"target": "motor1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.covers["motor1"] == snapshot

    def test_manual_sensor(self, snapshot: SnapshotAssertion) -> None:
        """Test manually defined sensor component."""
        cfg = HomeAssistantModuleDiscoveryConfig(
            address=ADDR,
            include=[],
            sensors={"var1": {"source": "var1"}},
        )
        cfg.inject_base_topic(BASE_TOPIC)
        assert cfg.sensors["var1"] == snapshot

    def test_extra_fields_forbidden(self) -> None:
        """Unknown top-level keys raise a validation error."""
        with pytest.raises(Exception):
            HomeAssistantModuleDiscoveryConfig(
                address=ADDR,
                unknown_key="value",  # type: ignore[call-arg]
            )
