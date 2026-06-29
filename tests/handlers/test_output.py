"""Tests for the output port handlers."""

from __future__ import annotations

import logging

import pytest
from pypck import inputs

from lcn2mqtt.handlers.output import (
    handle_input,
    handle_set,
    handle_set_brightness,
    handle_set_transition,
)
from lcn2mqtt.models.module import Module, OutputState


class TestHandleOutputInput:
    """Tests for the ModStatusOutput input handler."""

    @pytest.mark.parametrize(
        "brightness,expected_state",
        [
            (0.0, OutputState.OFF),
            (50.0, OutputState.ON),
            (100.0, OutputState.ON),
        ],
    )
    async def test_state_published_for_brightness(
        self, module: Module, brightness: float, expected_state: OutputState
    ) -> None:
        """The ON/OFF state is published based on the brightness value."""
        inp = inputs.ModStatusOutput(module.address, 0, brightness)
        messages = await handle_input(inp, module=module)
        state_msg = next(
            message for message in messages if message.topic == "output/1/state"
        )
        assert state_msg.payload == expected_state.name.lower()

    async def test_brightness_message_always_published(self, module: Module) -> None:
        """A brightness message is always included regardless of state change."""
        inp = inputs.ModStatusOutput(module.address, 0, 50.0)
        messages = await handle_input(inp, module=module)
        brightness_msg = next(
            message for message in messages if message.topic == "output/1/brightness"
        )
        assert brightness_msg.payload == "50.00"

    async def test_no_state_message_when_state_unchanged(self, module: Module) -> None:
        """No state message is emitted when the ON/OFF state does not change."""
        module.output1.state = OutputState.ON
        inp = inputs.ModStatusOutput(module.address, 0, 80.0)
        messages = await handle_input(inp, module=module)
        assert not any(message.topic == "output/1/state" for message in messages)

    async def test_no_brightness_message_when_brightness_unchanged(
        self, module: Module
    ) -> None:
        """No brightness message is emitted when the brightness does not change."""
        module.output1.brightness = 80.0
        inp = inputs.ModStatusOutput(module.address, 0, 80.0)
        messages = await handle_input(inp, module=module)
        assert not any(message.topic == "output/1/brightness" for message in messages)


class TestHandleSetBrightness:
    """Tests for the set_brightness MQTT command handler."""

    async def test_valid_brightness_updates_module(
        self, module_with_conn: Module
    ) -> None:
        """A valid float payload updates output.brightness."""
        await handle_set_brightness(
            "output/1/set_brightness", "75.0", module=module_with_conn
        )
        assert module_with_conn.output1.brightness == 75.0

    async def test_invalid_payload_logs_warning_and_leaves_value(
        self, module_with_conn: Module, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-numeric payload logs a warning and does not alter brightness."""
        module_with_conn.output1.brightness = 50.0
        with caplog.at_level(logging.WARNING):
            await handle_set_brightness(
                "output/1/set_brightness", "bad", module=module_with_conn
            )
        assert module_with_conn.output1.brightness == 50.0
        assert any("brightness" in r.message.lower() for r in caplog.records)

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Module
    ) -> None:
        """An output index outside 1-4 is silently ignored."""
        await handle_set_brightness(
            "output/5/set_brightness", "50.0", module=module_with_conn
        )
        # No exception; nothing changed


class TestHandleSetTransition:
    """Tests for the set_transition MQTT command handler."""

    async def test_valid_transition_updates_module(
        self, module_with_conn: Module
    ) -> None:
        """A valid integer payload updates output.transition in ms."""
        await handle_set_transition(
            "output/1/set_transition", "1000", module=module_with_conn
        )
        assert module_with_conn.output1.transition == 1000

    async def test_invalid_payload_logs_warning(
        self, module_with_conn: Module, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-numeric payload logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_set_transition(
                "output/1/set_transition", "bad", module=module_with_conn
            )
        assert any("transition" in r.message.lower() for r in caplog.records)


class TestHandleSet:
    """Tests for the output set MQTT command handler."""

    async def test_on_when_off_calls_toggle(self, module_with_conn: Module) -> None:
        """'on' command when output is currently OFF triggers toggle_output."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.OFF
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "on", module=module_with_conn)
        module_with_conn._device_connection.toggle_output.assert_awaited_with(
            0, 0, to_memory=True
        )  # idx-1, ramp, to_memory

    async def test_on_when_already_on_calls_dim(self, module_with_conn: Module) -> None:
        """'on' command when output is already ON dims to the stored brightness."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.ON
        module_with_conn.output1.brightness = 80.0
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "on", module=module_with_conn)
        module_with_conn._device_connection.dim_output.assert_awaited_with(
            0, 80.0, 0
        )  # idx-1, brightness, ramp

    async def test_off_when_on_calls_toggle(self, module_with_conn: Module) -> None:
        """'off' command when output is ON triggers toggle_output."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.ON
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "off", module=module_with_conn)
        module_with_conn._device_connection.toggle_output.assert_awaited_with(
            0, 0, to_memory=True
        )  # idx-1, ramp, to_memory

    async def test_off_when_already_off_calls_dim(
        self, module_with_conn: Module
    ) -> None:
        """'off' command when output is already OFF dims to 0."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.OFF
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "off", module=module_with_conn)
        module_with_conn._device_connection.dim_output.assert_awaited_with(
            0,
            0.0,
            0,  # idx-1, brightness, ramp
        )

    async def test_numeric_payload_calls_dim(self, module_with_conn: Module) -> None:
        """A numeric string payload dims the output to that brightness."""
        assert module_with_conn._device_connection
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "60.0", module=module_with_conn)
        module_with_conn._device_connection.dim_output.assert_awaited_with(
            0,
            60.0,
            0,  # idx-1, brightness, ramp
        )

    async def test_brightness_clamped_to_100(self, module_with_conn: Module) -> None:
        """Brightness values above 100 are clamped to 100."""
        assert module_with_conn._device_connection
        await handle_set("output/1/set", "150.0", module=module_with_conn)
        _, call_args, _ = module_with_conn._device_connection.dim_output.mock_calls[0]
        brightness_arg = call_args[1]  # positional arg index 1
        assert brightness_arg <= 100.0

    async def test_invalid_payload_logs_warning(
        self, module_with_conn: Module, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-numeric, non-on/off payload logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_set("output/1/set", "invalid", module=module_with_conn)
        assert any("output" in record.message.lower() for record in caplog.records)
