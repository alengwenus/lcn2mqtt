"""Tests for the relay handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.relay import (
    handle_relay_status,
    handle_retained_state,
    handle_set,
)
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device, RelayState


class TestHandleRelayStatus:
    """Tests for the ModStatusRelays input handler."""

    async def test_all_relays_reported_on_first_call(self, module: Device) -> None:
        """All 8 relays produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        messages = list(handle_relay_status(inp, module=module))
        assert len(messages) == 8

    async def test_changed_relays_produce_messages(self, module: Device) -> None:
        """Only relays whose state actually changed emit a message."""
        states = [True, False, True] + [False] * 5
        inp = inputs.ModStatusRelays(module.address, states)
        messages = list(handle_relay_status(inp, module=module))
        topics = {m.topic for m in messages}
        assert "relay/1/state" in topics
        assert "relay/3/state" in topics

    @pytest.mark.parametrize(
        "state, expected_payload",
        [
            (True, "on"),
            (False, "off"),
        ],
    )
    async def test_on_state_produces_on_payload(
        self, module: Device, state: bool, expected_payload: str
    ) -> None:
        """A relay set to True publishes 'on'."""
        inp = inputs.ModStatusRelays(module.address, [state] + [False] * 7)
        messages = list(handle_relay_status(inp, module=module))
        msg = next(
            (message for message in messages if message.topic == "relay/1/state"), None
        )
        assert msg is not None
        assert msg.payload == expected_payload

    async def test_no_change_produces_no_messages(self, module: Device) -> None:
        """No messages are emitted when all relay states are unchanged."""
        inp = inputs.ModStatusRelays(module.address, [True, False] + [False] * 6)
        list(handle_relay_status(inp, module=module))
        messages = list(handle_relay_status(inp, module=module))
        assert messages == []


class TestHandleRelaySet:
    """Tests for the relay set MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_modifier",
        [
            ("on", lcn_defs.RelayStateModifier.ON),
            ("off", lcn_defs.RelayStateModifier.OFF),
            ("toggle", lcn_defs.RelayStateModifier.TOGGLE),
        ],
    )
    async def test_set_command_calls_control_relays(
        self,
        module_with_conn: Device,
        config: AppConfig,
        payload: str,
        expected_modifier: lcn_defs.RelayStateModifier,
    ) -> None:
        """Sending a set command calls the device's control_relays method with the correct modifier."""
        await handle_set("relay/1/set", payload, module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_relays.assert_awaited_once()
        states = conn.control_relays.call_args.args[0]
        assert states[0] == expected_modifier
        assert all(s == lcn_defs.RelayStateModifier.NOCHANGE for s in states[1:])

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unknown payload logs a warning and does not call the device."""
        with caplog.at_level(logging.WARNING):
            await handle_set("relay/1/set", "unknown", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_relays.assert_not_awaited()
        assert any("relay" in record.message.lower() for record in caplog.records)

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A relay index outside 1-8 is silently ignored."""
        await handle_set("relay/9/set", "on", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.control_relays.assert_not_awaited()


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("on", RelayState.ON),
            ("off", RelayState.OFF),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: RelayState,
    ) -> None:
        """Sending a retained state command updates the module's relay state."""
        assert module.relay1 is None
        await handle_retained_state("relay/1/state", payload, module, bridge)
        assert module.relay1 == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("relay/1/state", "unknown", module, bridge)
        assert any(
            "Invalid relay state payload" in record.message for record in caplog.records
        )
