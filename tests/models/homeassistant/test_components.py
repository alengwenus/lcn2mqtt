"""Tests for Home Assistant component models."""

from __future__ import annotations

import pytest
from pypck import lcn_defs
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.models.homeassistant.components import (
    BinarySensorComponent,
    ClimateComponent,
    CoverComponent,
    LightComponent,
    NumberComponent,
    SelectComponent,
    SensorComponent,
    SwitchComponent,
)

ADDR = LcnAddr(0, 7, False)
BASE_TOPIC = "lcntest"
PREFIX = f"{BASE_TOPIC}/module/0/7"


def make_switch(target: str, **kwargs) -> SwitchComponent:
    cmp = SwitchComponent(address=ADDR, identifier=target, target=target, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_light(target: str, **kwargs) -> LightComponent:
    cmp = LightComponent(address=ADDR, identifier=target, target=target, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_binary_sensor(source: str, **kwargs) -> BinarySensorComponent:
    cmp = BinarySensorComponent(
        address=ADDR, identifier=source, source=source, **kwargs
    )
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_sensor(source: str, **kwargs) -> SensorComponent:
    cmp = SensorComponent(address=ADDR, identifier=source, source=source, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_number(target: str, **kwargs) -> NumberComponent:
    cmp = NumberComponent(address=ADDR, identifier=target, target=target, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_select(target: str, **kwargs) -> SelectComponent:
    cmp = SelectComponent(address=ADDR, identifier=target, target=target, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


def make_cover(target: str, **kwargs) -> CoverComponent:
    cmp = CoverComponent(address=ADDR, identifier=target, target=target, **kwargs)
    cmp.set_base_topic(BASE_TOPIC)
    return cmp


class TestBaseComponentModel:
    """Tests for BaseComponentModel shared behaviour."""

    def test_default_name_capitalizes_identifier(self) -> None:
        """Default name is the identifier capitalized with underscores replaced."""
        sw = make_switch("relay1")
        assert sw.name == "Relay1"

    def test_custom_name_is_preserved(self) -> None:
        """Explicitly provided name is not overwritten."""
        sw = make_switch("relay1", name="Living room light")
        assert sw.name == "Living room light"

    def test_unique_id_auto_generated(self) -> None:
        """Unique ID is set from base_topic + address + platform + identifier."""
        sw = make_switch("relay1")
        assert sw.unique_id == f"{BASE_TOPIC}_m000007_switch_relay1"

    def test_custom_unique_id_preserved(self) -> None:
        """Explicitly provided unique_id is not overwritten."""
        sw = make_switch("relay1", uniq_id="my_custom_id")
        assert sw.unique_id == "my_custom_id"

    def test_discovery_info_excludes_none_fields(self) -> None:
        """discovery_info() never includes keys whose value is None."""
        sw = make_switch("relay1")
        info = sw.discovery_info()
        assert all(v is not None for v in info.values())

    def test_discovery_info_contains_platform(self) -> None:
        """discovery_info() contains a 'platform' key."""
        sw = make_switch("relay1")
        info = sw.discovery_info()
        assert info["platform"] == "switch"

    def test_prefix_uses_module_addr(self) -> None:
        """The topic prefix reflects the module's segment and address IDs."""
        sw = make_switch("relay1")
        assert sw.prefix == PREFIX


class TestSwitchComponent:
    """Tests for SwitchComponent."""

    def test_relay_state_topic(self) -> None:
        """Relay switch state topic uses relay/<n>/state."""
        sw = make_switch("relay1")
        assert sw.state_topic == f"{PREFIX}/relay/1/state"

    def test_relay_command_topic(self) -> None:
        """Relay switch command topic uses relay/<n>/set."""
        sw = make_switch("relay1")
        assert sw.command_topic == f"{PREFIX}/relay/1/set"

    def test_relay_index_reflects_port(self) -> None:
        """Relay 3 uses index 3 in the topic."""
        sw = make_switch("relay3")
        assert sw.state_topic == f"{PREFIX}/relay/3/state"

    def test_output_state_topic(self) -> None:
        """Output switch state topic uses output/<n>/state."""
        sw = make_switch("output2")
        assert sw.state_topic == f"{PREFIX}/output/2/state"

    def test_output_command_topic(self) -> None:
        """Output switch command topic uses output/<n>/set."""
        sw = make_switch("output2")
        assert sw.command_topic == f"{PREFIX}/output/2/set"

    def test_custom_state_topic_not_overwritten(self) -> None:
        """A user-supplied state_topic is not replaced by the default."""
        sw = SwitchComponent(
            address=ADDR,
            identifier="relay1",
            target="relay1",
            state_topic="custom/state",
        )
        sw.set_base_topic(BASE_TOPIC)
        assert sw.state_topic == "custom/state"

    def test_invalid_target_raises(self) -> None:
        """An unrecognized target string raises ValueError."""
        with pytest.raises(ValueError):
            SwitchComponent(address=ADDR, identifier="x", target="invalid_port")

    def test_platform_is_switch(self) -> None:
        """Platform field is 'switch'."""
        sw = make_switch("relay1")
        assert sw.platform == "switch"


class TestLightComponent:
    """Tests for LightComponent (output-based dimmable light)."""

    def test_output_brightness_state_topic(self) -> None:
        """Output light exposes a brightness_state_topic."""
        lt = make_light("output1")
        assert lt.brightness_state_topic == f"{PREFIX}/output/1/brightness"

    def test_output_brightness_command_topic(self) -> None:
        """Output light exposes a brightness_command_topic."""
        lt = make_light("output1")
        assert lt.brightness_command_topic == f"{PREFIX}/output/1/set_brightness"

    def test_brightness_scale_default(self) -> None:
        """Default brightness scale is 100."""
        lt = make_light("output1")
        assert lt.brightness_scale == 100

    def test_relay_target_has_no_brightness_topics(self) -> None:
        """A relay-based LightComponent does not set brightness topics."""
        lt = make_light("relay1")
        assert lt.brightness_state_topic is None
        assert lt.brightness_command_topic is None

    def test_platform_is_light(self) -> None:
        """Platform field is 'light'."""
        lt = make_light("output1")
        assert lt.platform == "light"


class TestBinarySensorComponent:
    """Tests for BinarySensorComponent."""

    def test_state_topic(self) -> None:
        """Binary sensor state topic uses binsensor/<n>/state."""
        bs = make_binary_sensor("binsensor1")
        assert bs.state_topic == f"{PREFIX}/binsensor/1/state"

    def test_index_reflects_port(self) -> None:
        """BinSensor 3 uses index 3 in the topic."""
        bs = make_binary_sensor("binsensor3")
        assert bs.state_topic == f"{PREFIX}/binsensor/3/state"

    def test_invalid_source_raises(self) -> None:
        """An unrecognized source string raises ValueError."""
        with pytest.raises(ValueError):
            BinarySensorComponent(address=ADDR, identifier="x", source="notaport")

    def test_platform_is_binary_sensor(self) -> None:
        """Platform field is 'binary_sensor'."""
        bs = make_binary_sensor("binsensor1")
        assert bs.platform == "binary_sensor"

    def test_default_payloads(self) -> None:
        """Default payload_on and payload_off are 'on' and 'off'."""
        bs = make_binary_sensor("binsensor1")
        assert bs.payload_on == "on"
        assert bs.payload_off == "off"


class TestSensorComponent:
    """Tests for SensorComponent (variable, setpoint, threshold, LED)."""

    def test_variable_state_topic(self) -> None:
        """Variable sensor uses variable/<n>/state topic."""
        s = make_sensor("var1")
        assert s.state_topic == f"{PREFIX}/variable/1/state"

    def test_setpoint_state_topic(self) -> None:
        """Setpoint sensor uses setpoint/<n>/state topic."""
        s = make_sensor("setpoint1")
        assert s.state_topic == f"{PREFIX}/setpoint/1/state"

    def test_threshold_state_topic(self) -> None:
        """Threshold sensor uses threshold/<register>/<idx>/state topic."""
        s = make_sensor("thrs1")
        assert s.state_topic == f"{PREFIX}/threshold/1/1/state"

    def test_led_state_topic(self) -> None:
        """LED sensor uses led/<n>/state topic."""
        s = make_sensor("led1")
        assert s.state_topic == f"{PREFIX}/led/1/state"

    def test_invalid_source_raises(self) -> None:
        """An unrecognized source string raises ValueError."""
        with pytest.raises(ValueError):
            SensorComponent(address=ADDR, identifier="x", source="notavar")

    def test_platform_is_sensor(self) -> None:
        """Platform field is 'sensor'."""
        s = make_sensor("var1")
        assert s.platform == "sensor"


class TestNumberComponent:
    """Tests for NumberComponent (variable, setpoint, threshold)."""

    def test_variable_topics(self) -> None:
        """Variable number component uses variable/<n>/(state|set) topics."""
        n = make_number("var1")
        assert n.state_topic == f"{PREFIX}/variable/1/state"
        assert n.command_topic == f"{PREFIX}/variable/1/set"

    def test_setpoint_topics(self) -> None:
        """Setpoint number component uses setpoint/<n>/(state|set) topics."""
        n = make_number("setpoint1")
        assert n.state_topic == f"{PREFIX}/setpoint/1/state"
        assert n.command_topic == f"{PREFIX}/setpoint/1/set"

    def test_threshold_topics(self) -> None:
        """Threshold number component uses threshold/<r>/<n>/(state|set) topics."""
        n = make_number("thrs1")
        assert n.state_topic == f"{PREFIX}/threshold/1/1/state"
        assert n.command_topic == f"{PREFIX}/threshold/1/1/set"

    def test_invalid_target_raises(self) -> None:
        """An unrecognized target string raises ValueError."""
        with pytest.raises(ValueError):
            NumberComponent(address=ADDR, identifier="x", target="notavar")

    def test_platform_is_number(self) -> None:
        """Platform field is 'number'."""
        n = make_number("var1")
        assert n.platform == "number"


class TestSelectComponent:
    """Tests for SelectComponent (LED state selector)."""

    def test_state_topic(self) -> None:
        """Select component state topic uses led/<n>/state."""
        s = make_select("led1")
        assert s.state_topic == f"{PREFIX}/led/1/state"

    def test_command_topic(self) -> None:
        """Select component command topic uses led/<n>/set."""
        s = make_select("led1")
        assert s.command_topic == f"{PREFIX}/led/1/set"

    def test_options_match_led_states(self) -> None:
        """Options list matches LedStatus names in lowercase."""
        s = make_select("led1")
        expected = [state.name.lower() for state in lcn_defs.LedStatus]
        assert s.options == expected

    def test_invalid_target_raises(self) -> None:
        """An unrecognized target string raises ValueError."""
        with pytest.raises(ValueError):
            SelectComponent(address=ADDR, identifier="x", target="notaled")

    def test_platform_is_select(self) -> None:
        """Platform field is 'select'."""
        s = make_select("led1")
        assert s.platform == "select"


class TestCoverComponent:
    """Tests for CoverComponent (motor-driven cover)."""

    def test_state_topic(self) -> None:
        """Cover state topic uses motor/<n>/state."""
        c = make_cover("motor1")
        assert c.state_topic == f"{PREFIX}/motor/1/state"

    def test_command_topic(self) -> None:
        """Cover command topic uses motor/<n>/set."""
        c = make_cover("motor1")
        assert c.command_topic == f"{PREFIX}/motor/1/set"

    def test_motor_index_reflects_port(self) -> None:
        """Motor 2 uses index 2 in the topic."""
        c = make_cover("motor2")
        assert c.state_topic == f"{PREFIX}/motor/2/state"

    def test_invalid_target_raises(self) -> None:
        """An unrecognized target string raises ValueError."""
        with pytest.raises(ValueError):
            CoverComponent(address=ADDR, identifier="x", target="notamotor")

    def test_platform_is_cover(self) -> None:
        """Platform field is 'cover'."""
        c = make_cover("motor1")
        assert c.platform == "cover"


class TestClimateComponent:
    """Tests for ClimateComponent."""

    def _make_climate(self, **kwargs) -> ClimateComponent:
        defaults = {
            "address": ADDR,
            "identifier": "climate1",
            "temperature": "R1VARSETPOINT",
            "current_temperature": "VAR1",
        }
        defaults.update(kwargs)
        cmp = ClimateComponent(**defaults)
        cmp.set_base_topic(BASE_TOPIC)
        return cmp

    def test_temperature_state_topic(self) -> None:
        """Temperature state topic uses setpoint/<n>/state."""
        c = self._make_climate()
        assert c.temperature_state_topic == f"{PREFIX}/setpoint/1/state"

    def test_temperature_command_topic(self) -> None:
        """Temperature command topic uses setpoint/<n>/set."""
        c = self._make_climate()
        assert c.temperature_command_topic == f"{PREFIX}/setpoint/1/set"

    def test_current_temperature_topic(self) -> None:
        """Current temperature topic uses variable/<n>/state."""
        c = self._make_climate()
        assert c.current_temperature_topic == f"{PREFIX}/variable/1/state"

    def test_mode_topics_match_temperature_register(self) -> None:
        """Mode topics reference the same setpoint register as temperature."""
        c = self._make_climate()
        assert c.mode_state_topic == f"{PREFIX}/setpoint/1/locked"
        assert c.mode_command_topic == f"{PREFIX}/setpoint/1/lock"

    def test_default_modes(self) -> None:
        """Default modes are ['off', 'heat']."""
        c = self._make_climate()
        assert c.modes == ["off", "heat"]

    def test_invalid_temperature_raises(self) -> None:
        """A non-setpoint temperature raises ValueError."""
        with pytest.raises(ValueError):
            ClimateComponent(
                address=ADDR,
                identifier="c",
                temperature="VAR1",
                current_temperature="VAR2",
            )

    def test_invalid_current_temperature_raises(self) -> None:
        """A non-variable current_temperature raises ValueError."""
        with pytest.raises(ValueError):
            ClimateComponent(
                address=ADDR,
                identifier="c",
                temperature="R1VARSETPOINT",
                current_temperature="R1VARSETPOINT",
            )

    def test_missing_temperature_raises(self) -> None:
        """Missing temperature field raises ValueError."""
        with pytest.raises(ValueError):
            ClimateComponent(
                address=ADDR,
                identifier="c",
                current_temperature="VAR1",
            )

    def test_platform_is_climate(self) -> None:
        """Platform field is 'climate'."""
        c = self._make_climate()
        assert c.platform == "climate"
