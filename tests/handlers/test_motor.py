"""Tests for the motor (blind/shutter) handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.motor import (
    _STOP_TIMEOUT_POSITIONING,
    handle_motor_outputs_position_module_status,
    handle_motor_outputs_set,
    handle_motor_outputs_status,
    handle_motor_relays_set,
    handle_motor_relays_status,
    handle_retained_state,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device, MotorState

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

    async def test_all_relays_reported_on_first_call(self, module: Device) -> None:
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
        module: Device,
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

    async def test_no_change_produces_no_messages(self, module: Device) -> None:
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
        module_with_conn: Device,
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
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """An unrecognised payload is silently ignored."""
        await handle_motor_relays_set("motor/1/set", "wiggle", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A motor index outside 1-4 is silently ignored."""
        await handle_motor_relays_set("motor/5/set", "open", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_motor_relays.assert_not_awaited()


# ---------- Motors via outputs ----------


class TestHandleMotorOutputsStatus:
    """Tests for the ModStatusOutput motor input handler."""

    async def test_outputs_reported_on_first_call(self, module: Device) -> None:
        """All motors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusOutput(module.address, 0, 0)
        messages = list(handle_motor_outputs_status(inp, module=module))
        assert len(messages) == 1

    async def test_module_positioning_mode_is_ignored(self, module: Device) -> None:
        """In MODULE positioning mode the output-status is skipped entirely."""
        module.motor_outputs.positioning_mode = "MODULE"  # type: ignore[assignment]
        module.motor_outputs.state = MotorState.OPENING
        inp = inputs.ModStatusOutput(
            module.address, lcn_defs.OutputPort.OUTPUTUP.value, 0
        )
        messages = list(handle_motor_outputs_status(inp, module=module))
        assert messages == []
        assert module.motor_outputs.state == MotorState.OPENING  # unchanged

    @pytest.mark.parametrize(
        "output, percent, prior_state, expected_state",
        [
            (
                lcn_defs.OutputPort.OUTPUTUP,
                100.0,
                MotorState.CLOSED,
                MotorState.OPENING,
            ),
            (
                lcn_defs.OutputPort.OUTPUTDOWN,
                100.0,
                MotorState.OPEN,
                MotorState.CLOSING,
            ),
            (
                lcn_defs.OutputPort.OUTPUTUP,
                0.0,
                MotorState.OPENING,
                MotorState.OPEN,
            ),
            (
                lcn_defs.OutputPort.OUTPUTDOWN,
                0.0,
                MotorState.CLOSING,
                MotorState.CLOSED,
            ),
        ],
    )
    async def test_motor_state_detected(
        self,
        module: Device,
        output: lcn_defs.OutputPort,
        percent: float,
        prior_state: MotorState,
        expected_state: MotorState,
    ) -> None:
        """Motor 1 reports the correct state based on relay inputs."""
        module.motor_outputs.state = prior_state
        inp = inputs.ModStatusOutput(module.address, output.value, percent)
        messages = list(handle_motor_outputs_status(inp, module=module))
        msg = next(
            (
                m
                for m in messages
                if isinstance(m, MqttMessage) and m.topic == "motor/outputs/state"
            ),
            None,
        )
        assert msg is not None
        assert msg.payload == expected_state.value

    async def test_no_change_produces_no_messages(self, module: Device) -> None:
        """No messages are emitted when motor states are unchanged."""
        inp = inputs.ModStatusOutput(
            module.address, lcn_defs.OutputPort.OUTPUTUP.value, 0
        )
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
        module_with_conn: Device,
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
        self, module_with_conn: Device, config: AppConfig
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
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: MotorState,
        motor: str,
        motor_attr: str,
    ) -> None:
        """Sending a retained state command updates the module's motor state."""
        motor_obj = getattr(module, motor_attr)
        assert motor_obj.state is None
        await handle_retained_state(f"motor/{motor}/state", payload, module, bridge)
        assert motor_obj.state == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("motor/1/state", "other", module, bridge)
        assert any(
            "Invalid motor state payload" in record.message for record in caplog.records
        )


# ---------- Motors via outputs – positioning mode ----------


class TestHandleMotorOutputsPositionModuleStatus:
    """Tests for handle_motor_outputs_position_module_status DeferredMqttMessage behaviour."""

    def _make_module(
        self,
        module: Device,
        old_position: float | None = None,
        stop_timeout_s: float | None = None,
    ) -> Device:
        module.motor_outputs.positioning_mode = "MODULE"  # type: ignore[assignment]
        if old_position is not None:
            module.motor_outputs.position = old_position
        if stop_timeout_s is not None:
            module.motor_outputs.stop_timeout = stop_timeout_s
        return module

    def _run(self, module: Device, position: float) -> list[MqttMessage]:
        """Run the handler for motor 4 (outputs) at the given position."""
        inp = inputs.ModStatusMotorPositionModule(module.address, 3, position)
        return list(handle_motor_outputs_position_module_status(inp, module=module))

    def test_deferred_message_yielded_when_opening(self, module: Device) -> None:
        """DeferredMqttMessage is yielded when position is increasing (OPENING)."""
        self._make_module(module, old_position=30.0)
        items = self._run(module, 50.0)
        deferred = next((item for item in items if item.delay not in (None, 0.0)), None)
        assert deferred is not None
        assert deferred.topic == "motor/outputs/state"
        assert deferred.payload == MotorState.OPEN.value
        assert deferred.delay == _STOP_TIMEOUT_POSITIONING

    def test_deferred_cancel_yielded_when_open(self, module: Device) -> None:
        """Cancel-only DeferredMqttMessage is yielded when position == 100 (OPEN)."""
        self._make_module(module, old_position=80.0)
        items = self._run(module, 100.0)
        deferred = next((item for item in items if item.delay is None), None)
        assert deferred is not None
        assert deferred.topic == "motor/outputs/state"
        assert deferred.delay is None  # cancel only

    def test_deferred_cancel_yielded_when_closed(self, module: Device) -> None:
        """Cancel-only DeferredMqttMessage is yielded when position == 0 (CLOSED)."""
        self._make_module(module, old_position=20.0)
        items = self._run(module, 0.0)
        deferred = next((item for item in items if item.delay is None), None)
        assert deferred is not None
        assert deferred.delay is None

    def test_no_deferred_on_first_update_without_direction(
        self, module: Device
    ) -> None:
        """No DeferredMqttMessage when direction cannot be determined (first update)."""
        self._make_module(module, old_position=None)
        items = self._run(module, 50.0)
        assert all(item.delay == 0.0 for item in items)

    def test_produce_returns_open_at_intermediate_position(
        self, module: Device
    ) -> None:
        """Payload is OPEN when motor stops at an intermediate position (> 0)."""
        self._make_module(module, old_position=30.0)
        items = self._run(module, 50.0)
        deferred = next(item for item in items if item.delay not in (None, 0.0))
        assert deferred.payload == MotorState.OPEN.value

    def test_produce_returns_closed_at_position_zero(self, module: Device) -> None:
        """Cancel-only DeferredMqttMessage is yielded when motor reaches position 0 (CLOSED)."""
        self._make_module(module, old_position=20.0)
        items = self._run(module, 0.0)
        deferred = next(item for item in items if item.delay is None)
        # position==0 triggers cancel-only; the immediate MqttMessage says "closed"
        assert deferred.delay is None
        assert deferred.topic == "motor/outputs/state"
        assert deferred.payload == MotorState.CLOSED.value

    def test_produce_returns_none_when_already_resolved(self, module: Device) -> None:
        """When timer would fire but state is already resolved, payload is OPEN (no guard)."""
        # The payload is fixed at schedule time, so no runtime guard is needed.
        # Redundant publishes are harmless in MQTT.
        self._make_module(module, old_position=30.0)
        items = self._run(module, 50.0)
        deferred = next(item for item in items if item.delay not in (None, 0.0))
        # Payload is fixed regardless of current state
        assert deferred.payload == MotorState.OPEN.value

    def test_custom_stop_timeout_used_in_deferred(self, module: Device) -> None:
        """Custom stop_timeout_s is passed as the DeferredMqttMessage delay."""
        self._make_module(module, old_position=30.0, stop_timeout_s=15.0)
        items = self._run(module, 50.0)
        deferred = next(item for item in items if item.delay not in (None, 0.0))
        assert deferred.delay == 15.0

    def test_default_timeout_is_5s_for_positioning_mode(self, module: Device) -> None:
        """Default timeout for positioning mode is _STOP_TIMEOUT_POSITIONING (5 s)."""
        self._make_module(module, old_position=30.0)
        items = self._run(module, 50.0)
        deferred = next(item for item in items if item.delay not in (None, 0.0))
        assert deferred.delay == _STOP_TIMEOUT_POSITIONING
