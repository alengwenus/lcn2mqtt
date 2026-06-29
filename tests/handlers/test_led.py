"""Tests for the LED handlers."""

from __future__ import annotations

import logging

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.led import handle_command, handle_input
from lcn2mqtt.models.module import Module

_ALL_OFF = [lcn_defs.LedStatus.OFF] * 12
_ALL_LOGIC_OPS = [lcn_defs.LogicOpStatus.NONE] * 4


def _make_led_inp(
    states: list[lcn_defs.LedStatus], module: Module
) -> inputs.ModStatusLedsAndLogicOps:
    """Build a ModStatusLedsAndLogicOps input with the given LED states."""
    return inputs.ModStatusLedsAndLogicOps(module.address, states, _ALL_LOGIC_OPS)


class TestHandleLedInput:
    """Tests for the ModStatusLedsAndLogicOps input handler."""

    async def test_all_leds_reported_on_first_call(self, module: Module) -> None:
        """All 12 LEDs produce a message on the very first call (all were unknown)."""
        inp = _make_led_inp(_ALL_OFF, module)
        messages = await handle_input(inp, module=module)
        assert len(messages) == 12

    async def test_all_leds_covered_on_first_call(self, module: Module) -> None:
        """LEDs changing from unknown to states produce messages with correct payloads."""
        states = (
            [lcn_defs.LedStatus.ON] * 3
            + [lcn_defs.LedStatus.OFF] * 3
            + [lcn_defs.LedStatus.BLINK] * 3
            + [lcn_defs.LedStatus.FLICKER] * 3
        )
        messages = await handle_input(_make_led_inp(states, module), module=module)
        assert all(
            message.topic == f"led/{idx + 1}/state"
            and message.payload == state.name.lower()
            for idx, (state, message) in enumerate(zip(states, messages))
        )

    async def test_changed_leds_produce_messages(self, module: Module) -> None:
        """Only LEDs whose state changed produce a message."""
        await handle_input(_make_led_inp(_ALL_OFF, module), module=module)
        states = [lcn_defs.LedStatus.ON] + [lcn_defs.LedStatus.OFF] * 11
        messages = await handle_input(_make_led_inp(states, module), module=module)
        assert len(messages) == 1
        assert messages[0].topic == "led/1/state"
        assert messages[0].payload == "on"

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = _make_led_inp(_ALL_OFF, module)
        await handle_input(inp, module=module)
        messages = await handle_input(inp, module=module)
        assert messages == []


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
        module_with_conn: Module,
        payload: str,
        expected_status: lcn_defs.LedStatus,
    ) -> None:
        """Payload calls control_led with the expected LedStatus."""
        await handle_command("led/1/set", payload, module=module_with_conn)
        conn = module_with_conn._device_connection
        conn.control_led.assert_awaited_once()
        _, (_, status), _ = conn.control_led.mock_calls[0]  # name, args, kwargs
        assert status == expected_status

    async def test_set_command_also_requests_status(
        self, module_with_conn: Module
    ) -> None:
        """After sending the command, LED status is requested from the device."""
        await handle_command("led/1/set", "on", module=module_with_conn)
        module_with_conn._device_connection.request_status_leds_and_logic_ops.assert_awaited_once()

    async def test_invalid_payload_logs_warning(
        self, module_with_conn: Module, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown LED state payload logs a warning and does not call the device."""
        with caplog.at_level(logging.WARNING):
            await handle_command("led/1/set", "rainbow", module=module_with_conn)
        module_with_conn._device_connection.control_led.assert_not_awaited()
        assert any("led" in record.message.lower() for record in caplog.records)
