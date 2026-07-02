"""Tests for the motor (blind/shutter) handlers."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.motor import handle_relays_status, handle_set
from lcn2mqtt.models.module import Module, MotorState


def _relay_states(motor0_on: bool, motor0_down: bool) -> list[bool]:
    """Build an 8-relay state list for motor 0 only; all other motors are off."""
    # Motor 0 uses relay 0 (on/off) and relay 1 (direction: True=down/closing)
    s = [False] * 8
    s[0] = motor0_on
    s[1] = motor0_down
    return s


class TestHandleMotorStatus:
    """Tests for the ModStatusRelays motor input handler."""

    async def test_all_relays_reported_on_first_call(self, module: Module) -> None:
        """All 4 motors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        messages = list(handle_relays_status(inp, module=module))
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
        messages = list(handle_relays_status(inp, module=module))
        msg = next(
            (
                message
                for message in messages
                if message.topic == "motor_relays/1/state"
            ),
            None,
        )
        assert msg is not None
        assert msg.payload == expected_state.value

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """No messages are emitted when motor states are unchanged."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        list(handle_relays_status(inp, module=module))
        messages = list(handle_relays_status(inp, module=module))
        assert messages == []


class TestHandleMotorSet:
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
        payload: str,
        expected_modifier: lcn_defs.MotorStateModifier,
    ) -> None:
        """The set command calls the device connection's control_motor_relays method."""
        await handle_set("motor_relays/1/set", payload, module=module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_awaited_once_with(0, expected_modifier)

    async def test_unknown_payload_does_not_call_device(
        self, module_with_conn: Module
    ) -> None:
        """An unrecognised payload is silently ignored."""
        await handle_set("motor_relays/1/set", "wiggle", module=module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Module
    ) -> None:
        """A motor index outside 1-4 is silently ignored."""
        await handle_set("motor_relays/5/set", "open", module=module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()
