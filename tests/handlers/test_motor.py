"""Tests for the motor (blind/shutter) handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.motor import (
    handle_motor_outputs_set,
    handle_motor_outputs_status,
    handle_motor_relays_set,
    handle_motor_relays_status,
    handle_retained_state,
)
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.module import Module, MotorState

# ---------- Motors via relays ----------


def _relay_states(motor0_on: bool, motor0_down: bool) -> list[bool]:
    """Build an 8-relay state list for motor 0 only; all other motors are off."""
    # Motor 0 uses relay 0 (on/off) and relay 1 (direction: True=down/closing)
    s = [False] * 8
    s[0] = motor0_on
    s[1] = motor0_down
    return s


class TestHandleMotorRelaysStatus:
    """Tests for the ModStatusRelays motor input handler."""

    async def test_all_relays_reported_on_first_call(self, module: Module) -> None:
        """All 4 motors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        messages = list(handle_motor_relays_status(inp, module=module))
        assert len(messages) == 4

    @pytest.mark.parametrize(
        "motor0_on, motor0_down, expected_state",
        [
            (True, False, MotorState.OPENING),
            (True, True, MotorState.CLOSING),
            (False, True, MotorState.CLOSED),
            (False, False, MotorState.OPEN),
        ],
    )
    async def test_motor_state_detected(
        self,
        module: Module,
        motor0_on: bool,
        motor0_down: bool,
        expected_state: MotorState,
    ) -> None:
        """Motor 1 reports the correct state based on relay inputs."""
        inp = inputs.ModStatusRelays(
            module.address, _relay_states(motor0_on=motor0_on, motor0_down=motor0_down)
        )
        messages = list(handle_motor_relays_status(inp, module=module))
        msg = next(
            (message for message in messages if message.topic == "motor/1/state"),
            None,
        )
        assert msg is not None
        assert msg.payload == expected_state.value

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """No messages are emitted when motor states are unchanged."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        list(handle_motor_relays_status(inp, module=module))
        messages = list(handle_motor_relays_status(inp, module=module))
        assert messages == []


class TestHandleMotorRelaysSet:
    """Tests for the motor_relays set MQTT command handler."""

    @pytest.mark.parametrize(
        "payload, expected_modifier",
        [
            ("open", lcn_defs.MotorStateModifier.UP),
            ("close", lcn_defs.MotorStateModifier.DOWN),
            ("stop", lcn_defs.MotorStateModifier.STOP),
            ("up", lcn_defs.MotorStateModifier.UP),
            ("down", lcn_defs.MotorStateModifier.DOWN),
        ],
    )
    async def test_set_calls_control_motor_relays_command(
        self,
        module_with_conn: Module,
        config: AppConfig,
        payload: str,
        expected_modifier: lcn_defs.MotorStateModifier,
    ) -> None:
        """The set command calls the device connection's control_motor_relays method."""
        await handle_motor_relays_set("motor/1/set", payload, module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_awaited_once_with(
            0, expected_modifier, lcn_defs.MotorPositioningMode.NONE
        )

    async def test_unknown_payload_does_not_call_device(
        self, module_with_conn: Module, config: AppConfig
    ) -> None:
        """An unrecognised payload is silently ignored."""
        await handle_motor_relays_set("motor/1/set", "wiggle", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Module, config: AppConfig
    ) -> None:
        """A motor index outside 1-4 is silently ignored."""
        await handle_motor_relays_set("motor/5/set", "open", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()


# ---------- Motors via outputs ----------


class TestHandleMotorOutputsStatus:
    """Tests for the ModStatusOutput motor input handler."""

    async def test_outputs_reported_on_first_call(self, module: Module) -> None:
        """All 4 motors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusOutput(module.address, 0, 0)
        messages = list(handle_motor_outputs_status(inp, module=module))
        assert len(messages) == 1

    @pytest.mark.parametrize(
        "output_id, percent, prior_state, expected_state",
        [
            (0, 100.0, MotorState.CLOSED, MotorState.OPENING),
            (1, 100.0, MotorState.CLOSED, MotorState.CLOSING),
            (0, 0.0, MotorState.CLOSING, MotorState.CLOSED),
            (0, 0.0, MotorState.OPENING, MotorState.OPEN),
        ],
    )
    async def test_motor_state_detected(
        self,
        module: Module,
        output_id: int,
        percent: float,
        prior_state: MotorState,
        expected_state: MotorState,
    ) -> None:
        """Motor 1 reports the correct state based on relay inputs."""
        module.motor_outputs.state = prior_state
        inp = inputs.ModStatusOutput(module.address, output_id, percent)
        messages = list(handle_motor_outputs_status(inp, module=module))
        msg = next(
            (message for message in messages if message.topic == "motor/outputs/state"),
            None,
        )
        assert msg is not None
        assert msg.payload == expected_state.value

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """No messages are emitted when motor states are unchanged."""
        inp = inputs.ModStatusOutput(module.address, 0, 0)
        list(handle_motor_outputs_status(inp, module=module))
        messages = list(handle_motor_outputs_status(inp, module=module))
        assert messages == []


class TestHandleMotorOutputsSet:
    """Tests for the motor_outputs set MQTT command handler."""

    @pytest.mark.parametrize(
        "payload, expected_modifier",
        [
            ("open", lcn_defs.MotorStateModifier.UP),
            ("close", lcn_defs.MotorStateModifier.DOWN),
            ("stop", lcn_defs.MotorStateModifier.STOP),
            ("up", lcn_defs.MotorStateModifier.UP),
            ("down", lcn_defs.MotorStateModifier.DOWN),
        ],
    )
    async def test_set_calls_control_motor_outputs_command(
        self,
        module_with_conn: Module,
        config: AppConfig,
        payload: str,
        expected_modifier: lcn_defs.MotorStateModifier,
    ) -> None:
        """The set command calls the device connection's control_motor_outputs method."""
        reverse_time = module_with_conn.motor_outputs.reverse_time
        await handle_motor_outputs_set(
            "motor/outputs/set", payload, module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_outputs.assert_awaited_once_with(
            expected_modifier, reverse_time
        )

    async def test_unknown_payload_does_not_call_device(
        self, module_with_conn: Module, config: AppConfig
    ) -> None:
        """An unrecognised payload is silently ignored."""
        await handle_motor_outputs_set(
            "motor/outputs/set", "wiggle", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_outputs.assert_not_awaited()


# ---------- Retained state ----------


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "motor, motor_attr",
        [("1", "motor1"), ("outputs", "motor_outputs")],
    )
    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("open", MotorState.OPEN),
            ("closed", MotorState.CLOSED),
            ("opening", MotorState.OPENING),
            ("closing", MotorState.CLOSING),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Module,
        config: AppConfig,
        payload: str,
        expected_state: MotorState,
        motor: str,
        motor_attr: str,
    ) -> None:
        """Sending a retained state command updates the module's motor state."""
        motor_obj = getattr(module, motor_attr)
        assert motor_obj.state is None
        await handle_retained_state(f"motor/{motor}/state", payload, module, config)
        assert motor_obj.state == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Module, config: AppConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("motor/1/state", "unknown", module, config)
        assert any(
            "Invalid motor state payload" in record.message for record in caplog.records
        )
