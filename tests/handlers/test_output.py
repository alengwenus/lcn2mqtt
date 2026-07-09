"""Tests for the output port handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs

from lcn2mqtt.handlers.output import (
    handle_input,
    handle_retained_state,
    handle_set,
    handle_set_brightness,
    handle_set_transition,
)
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device, OutputState


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
        self, module: Device, brightness: float, expected_state: OutputState
    ) -> None:
        """The ON/OFF state is published based on the brightness value."""
        inp = inputs.ModStatusOutput(module.address, 0, brightness)
        messages = list(handle_input(inp, module=module))
        state_msg = next(
            message for message in messages if message.topic == "output/1/state"
        )
        assert state_msg.payload == expected_state.name.lower()

    async def test_brightness_message_always_published(self, module: Device) -> None:
        """A brightness message is always included regardless of state change."""
        inp = inputs.ModStatusOutput(module.address, 0, 50.0)
        messages = list(handle_input(inp, module=module))
        brightness_msg = next(
            message for message in messages if message.topic == "output/1/brightness"
        )
        assert brightness_msg.payload == "50.00"

    async def test_no_state_message_when_state_unchanged(self, module: Device) -> None:
        """No state message is emitted when the ON/OFF state does not change."""
        module.output1.state = OutputState.ON
        inp = inputs.ModStatusOutput(module.address, 0, 80.0)
        messages = list(handle_input(inp, module=module))
        assert not any(message.topic == "output/1/state" for message in messages)

    async def test_no_brightness_message_when_brightness_unchanged(
        self, module: Device
    ) -> None:
        """No brightness message is emitted when the brightness does not change."""
        module.output1.brightness = 80.0
        inp = inputs.ModStatusOutput(module.address, 0, 80.0)
        messages = list(handle_input(inp, module=module))
        assert not any(message.topic == "output/1/brightness" for message in messages)


class TestHandleSetBrightness:
    """Tests for the set_brightness MQTT command handler."""

    async def test_valid_brightness_updates_module(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A valid float payload updates output.brightness."""
        await handle_set_brightness(
            "output/1/set_brightness", "75.0", module_with_conn, config
        )
        assert module_with_conn.output1.brightness == 75.0

    async def test_invalid_payload_logs_warning_and_leaves_value(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric payload logs a warning and does not alter brightness."""
        module_with_conn.output1.brightness = 50.0
        with caplog.at_level(logging.WARNING):
            await handle_set_brightness(
                "output/1/set_brightness", "bad", module_with_conn, config
            )
        assert module_with_conn.output1.brightness == 50.0
        assert any("brightness" in r.message.lower() for r in caplog.records)

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """An output index outside 1-4 is silently ignored."""
        await handle_set_brightness(
            "output/5/set_brightness", "50.0", module_with_conn, config
        )
        # No exception; nothing changed


class TestHandleSetTransition:
    """Tests for the set_transition MQTT command handler."""

    async def test_valid_transition_updates_module(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A valid integer payload updates output.transition in ms."""
        await handle_set_transition(
            "output/1/set_transition", "1000", module_with_conn, config
        )
        assert module_with_conn.output1.transition == 1000

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric payload logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_set_transition(
                "output/1/set_transition", "bad", module_with_conn, config
            )
        assert any("transition" in r.message.lower() for r in caplog.records)


class TestHandleSet:
    """Tests for the output set MQTT command handler."""

    async def test_on_when_off_calls_toggle(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """'on' command when output is currently OFF triggers toggle_output."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.OFF
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "on", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.toggle_output.assert_awaited_with(
            0, 0, to_memory=True
        )  # idx-1, ramp, to_memory

    async def test_on_when_already_on_calls_dim(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """'on' command when output is already ON dims to the stored brightness."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.ON
        module_with_conn.output1.brightness = 80.0
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "on", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.dim_output.assert_awaited_with(0, 80.0, 0)  # idx-1, brightness, ramp

    async def test_off_when_on_calls_toggle(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """'off' command when output is ON triggers toggle_output."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.ON
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "off", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.toggle_output.assert_awaited_with(
            0, 0, to_memory=True
        )  # idx-1, ramp, to_memory

    async def test_off_when_already_off_calls_dim(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """'off' command when output is already OFF dims to 0."""
        assert module_with_conn._device_connection
        module_with_conn.output1.state = OutputState.OFF
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "off", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.dim_output.assert_awaited_with(
            0,
            0.0,
            0,  # idx-1, brightness, ramp
        )

    async def test_numeric_payload_calls_dim(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A numeric string payload dims the output to that brightness."""
        assert module_with_conn._device_connection
        module_with_conn.output1.transition = 0
        await handle_set("output/1/set", "60.0", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.dim_output.assert_awaited_with(
            0,
            60.0,
            0,  # idx-1, brightness, ramp
        )

    async def test_brightness_clamped_to_100(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Brightness values above 100 are clamped to 100."""
        assert module_with_conn._device_connection
        await handle_set("output/1/set", "150.0", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        _, call_args, _ = conn.dim_output.mock_calls[0]
        brightness_arg = call_args[1]  # positional arg index 1
        assert brightness_arg <= 100.0

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric, non-on/off payload logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_set("output/1/set", "invalid", module_with_conn, config)
        assert any("output" in record.message.lower() for record in caplog.records)


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("on", OutputState.ON),
            ("off", OutputState.OFF),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        config: AppConfig,
        payload: str,
        expected_state: OutputState,
    ) -> None:
        """Sending a retained state command updates the module's output state."""
        assert module.output1.state is None
        await handle_retained_state("output/1/state", payload, module, config)
        assert module.output1.state == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, config: AppConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("output/1/state", "unknown", module, config)
        assert any(
            "Invalid output state payload" in record.message
            for record in caplog.records
        )


class TestHandleRetainedBrightness:
    """Tests for the retained brightness MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_brightness",
        [
            ("100.", 100.0),
            ("50.5", 50.5),
            ("0.0", 0.0),
        ],
    )
    async def test_retained_brightness_updates_module(
        self,
        module: Device,
        config: AppConfig,
        payload: str,
        expected_brightness: float,
    ) -> None:
        """Sending a retained brightness command updates the module's output brightness."""
        assert module.output1.brightness is None
        await handle_retained_state("output/1/brightness", payload, module, config)
        assert module.output1.brightness == expected_brightness

    @pytest.mark.parametrize(
        "payload",
        [
            "unknown",
            "-10.0",
            "150.0",
        ],
    )
    async def test_invalid_payload_logs_warning(
        self,
        module: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
        payload: str,
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("output/1/brightness", payload, module, config)
        assert any(
            "Invalid output brightness payload" in record.message
            for record in caplog.records
        )
