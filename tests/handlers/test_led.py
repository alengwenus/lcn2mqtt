"""Tests for the LED handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.led import handle_command, handle_input, handle_retained_state
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.module import LedState, Module

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
        messages = list(handle_input(inp, module=module))
        assert len(messages) == 12

    async def test_all_leds_covered_on_first_call(self, module: Module) -> None:
        """LEDs changing from unknown to states produce messages with correct payloads."""
        states = (
            [lcn_defs.LedStatus.ON] * 3
            + [lcn_defs.LedStatus.OFF] * 3
            + [lcn_defs.LedStatus.BLINK] * 3
            + [lcn_defs.LedStatus.FLICKER] * 3
        )
        messages = list(handle_input(_make_led_inp(states, module), module=module))
        assert all(
            message.topic == f"led/{idx + 1}/state"
            and message.payload == state.name.lower()
            for idx, (state, message) in enumerate(zip(states, messages))
        )

    async def test_changed_leds_produce_messages(self, module: Module) -> None:
        """Only LEDs whose state changed produce a message."""
        list(handle_input(_make_led_inp(_ALL_OFF, module), module=module))
        states = [lcn_defs.LedStatus.ON] + [lcn_defs.LedStatus.OFF] * 11
        messages = list(handle_input(_make_led_inp(states, module), module=module))
        assert len(messages) == 1
        assert messages[0].topic == "led/1/state"
        assert messages[0].payload == "on"

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = _make_led_inp(_ALL_OFF, module)
        list(handle_input(inp, module=module))
        messages = list(handle_input(inp, module=module))
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
        self, module_with_conn: Module, config: AppConfig
    ) -> None:
        """After sending the command, LED status is requested from the device."""
        await handle_command("led/1/set", "on", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_leds_and_logic_ops.assert_awaited_once()

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Module,
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
        module: Module,
        config: AppConfig,
        payload: str,
        expected_state: LedState,
    ) -> None:
        """Sending a retained state command updates the module's LED state."""
        assert module.led1 is None
        await handle_retained_state("led/1/state", payload, module, config)
        assert module.led1 == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Module, config: AppConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("led/1/state", "unknown", module, config)
        assert any(
            "Invalid led state payload" in record.message for record in caplog.records
        )
