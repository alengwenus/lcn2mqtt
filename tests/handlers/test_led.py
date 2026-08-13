"""Tests for the LED handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, call, patch

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.led import (
    handle_command,
    handle_get_command,
    handle_input,
    handle_retained_state,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device, LedState

_ALL_OFF = [lcn_defs.LedStatus.OFF] * 12
_ALL_LOGIC_OPS = [lcn_defs.LogicOpStatus.NONE] * 4


def _make_led_inp(
    states: list[lcn_defs.LedStatus], module: Device
) -> inputs.ModStatusLedsAndLogicOps:
    """Build a ModStatusLedsAndLogicOps input with the given LED states."""
    return inputs.ModStatusLedsAndLogicOps(module.address, states, _ALL_LOGIC_OPS)


class TestHandleLedInput:
    """Tests for the ModStatusLedsAndLogicOps input handler."""

    async def test_all_leds_reported_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """All 12 LEDs produce a message on the very first call (all were unknown)."""
        inp = _make_led_inp(_ALL_OFF, module)
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(inp, module=module, bridge=bridge)
            assert mock_publish.call_count == 12

    async def test_all_leds_covered_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """LEDs changing from unknown to states produce messages with correct payloads."""
        states = (
            [lcn_defs.LedStatus.ON] * 3
            + [lcn_defs.LedStatus.OFF] * 3
            + [lcn_defs.LedStatus.BLINK] * 3
            + [lcn_defs.LedStatus.FLICKER] * 3
        )
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(_make_led_inp(states, module), module=module, bridge=bridge)

        assert mock_publish.call_args_list == [
            call(
                module.prefix,
                MqttMessage(
                    f"led/{idx + 1}/state",
                    state.name.lower(),
                    delay=0.0,
                ),
            )
            for idx, state in enumerate(states)
        ]

    async def test_changed_leds_produce_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Only LEDs whose state changed produce a message."""
        handle_input(_make_led_inp(_ALL_OFF, module), module=module, bridge=bridge)
        states = [lcn_defs.LedStatus.ON] + [lcn_defs.LedStatus.OFF] * 11
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(_make_led_inp(states, module), module=module, bridge=bridge)
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1].topic == "led/1/state"
            assert mock_publish.call_args[0][1].payload == "on"

    async def test_no_change_produces_no_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = _make_led_inp(_ALL_OFF, module)
        handle_input(inp, module=module, bridge=bridge)
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()


class TestHandleLedCommand:
    """Tests for the LED set MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_status",
        [
            ("on", lcn_defs.LedStatus.ON),
            ("off", lcn_defs.LedStatus.OFF),
            ("blink", lcn_defs.LedStatus.BLINK),
            ("flicker", lcn_defs.LedStatus.FLICKER),
        ],
    )
    async def test_set_command_calls_control_led(
        self,
        module_with_conn: Device,
        config: AppConfig,
        payload: str,
        expected_status: lcn_defs.LedStatus,
    ) -> None:
        """Payload calls control_led with the expected LedStatus."""
        await handle_command("led/1/set", payload, module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_led.assert_awaited_once()
        _, (_, status), _ = conn.control_led.mock_calls[0]  # name, args, kwargs
        assert status == expected_status

    async def test_set_command_also_requests_status(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """After sending the command, LED status is requested from the device."""
        await handle_command("led/1/set", "on", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.assert_awaited_once()

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unknown LED state payload logs a warning and does not call the device."""
        with caplog.at_level(logging.WARNING):
            await handle_command("led/1/set", "rainbow", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_led.assert_not_awaited()
        assert any("led" in record.message.lower() for record in caplog.records)


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("on", LedState.ON),
            ("off", LedState.OFF),
            ("blink", LedState.BLINK),
            ("flicker", LedState.FLICKER),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: LedState,
    ) -> None:
        """Sending a retained state command updates the module's LED state."""
        assert module.led1 is None
        await handle_retained_state("led/1/state", payload, module, bridge)
        assert module.led1 == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("led/1/state", "unknown", module, bridge)
        assert any(
            "Invalid led state payload" in record.message for record in caplog.records
        )


class TestHandleGetCommand:
    """Tests for the LED get MQTT command handler."""

    async def test_get_single_led_publishes_state(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """led/3/get requests status and publishes the state of LED 3 only."""
        states = list(_ALL_OFF)
        states[2] = lcn_defs.LedStatus.ON
        result_input = _make_led_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("led/3/get", "", module_with_conn, bridge)

        conn.request_status_leds_and_logic_ops.assert_awaited_once()
        mock_publish.assert_called_once_with(
            module_with_conn.prefix,
            MqttMessage("led/3/state", "on"),
        )

    async def test_get_all_leds_publishes_twelve_states(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """led/get requests status and publishes a state message for all 12 LEDs."""
        result_input = _make_led_inp(list(_ALL_OFF), module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("led/get", "", module_with_conn, bridge)

        conn.request_status_leds_and_logic_ops.assert_awaited_once()
        assert mock_publish.call_count == 12

    async def test_get_all_leds_correct_payloads(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """led/get publishes correct topic and payload for every LED."""
        states = (
            [lcn_defs.LedStatus.ON] * 3
            + [lcn_defs.LedStatus.OFF] * 3
            + [lcn_defs.LedStatus.BLINK] * 3
            + [lcn_defs.LedStatus.FLICKER] * 3
        )
        result_input = _make_led_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("led/get", "", module_with_conn, bridge)

        assert mock_publish.call_args_list == [
            call(
                module_with_conn.prefix,
                MqttMessage(f"led/{idx + 1}/state", state.name.lower()),
            )
            for idx, state in enumerate(states)
        ]

    @pytest.mark.parametrize(
        "subtopic, payload",
        [
            ("led/13/get", "off"),  # invalid index
            ("led/abc/get", "off"),  # non-integer index
            ("led/1/get", None),  # no state returned (None)
        ],
    )
    async def test_invalid_parameters_return_early(
        self,
        module_with_conn: Device,
        bridge: Bridge,
        subtopic: str,
        payload: str | None,
    ) -> None:
        """Invalid parameters and return values are ignored."""
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.return_value = payload
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command(subtopic, "", module_with_conn, bridge)
        if payload is not None:
            conn.request_status_leds_and_logic_ops.assert_not_awaited()
        else:
            conn.request_status_leds_and_logic_ops.assert_awaited_once()
        mock_publish.assert_not_called()
