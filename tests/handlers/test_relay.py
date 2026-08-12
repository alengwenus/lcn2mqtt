"""Tests for the relay handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, call, patch

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.relay import (
    handle_get_command,
    handle_relay_status,
    handle_retained_state,
    handle_set,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device, RelayState


class TestHandleRelayStatus:
    """Tests for the ModStatusRelays input handler."""

    async def test_all_relays_reported_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """All 8 relays produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusRelays(module.address, [False] * 8)
        with patch.object(bridge, "publish") as mock_publish:
            handle_relay_status(inp, module=module, bridge=bridge)
        assert mock_publish.call_count == 8

    async def test_changed_relays_produce_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Only relays whose state actually changed emit a message."""
        states = [True, False, True] + [False] * 5
        inp = inputs.ModStatusRelays(module.address, states)
        with patch.object(bridge, "publish") as mock_publish:
            handle_relay_status(inp, module=module, bridge=bridge)

        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("relay/1/state", "on", delay=0.0),
        )
        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("relay/3/state", "on", delay=0.0),
        )

    @pytest.mark.parametrize(
        "state, expected_payload",
        [
            (True, "on"),
            (False, "off"),
        ],
    )
    async def test_on_state_produces_on_payload(
        self, module: Device, bridge: Bridge, state: bool, expected_payload: str
    ) -> None:
        """A relay set to True publishes 'on'."""
        inp = inputs.ModStatusRelays(module.address, [state] + [False] * 7)
        with patch.object(bridge, "publish") as mock_publish:
            handle_relay_status(inp, module=module, bridge=bridge)
        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("relay/1/state", expected_payload, delay=0.0),
        )

    async def test_no_change_produces_no_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """No messages are emitted when all relay states are unchanged."""
        inp = inputs.ModStatusRelays(module.address, [True, False] + [False] * 6)
        handle_relay_status(inp, module=module, bridge=bridge)
        with patch.object(bridge, "publish") as mock_publish:
            handle_relay_status(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()


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


class TestHandleGetCommand:
    """Tests for the relay/+/get and relay/get MQTT command handler."""

    def _make_relay_inp(
        self, states: list[bool], module: Device
    ) -> inputs.ModStatusRelays:
        """Build a ModStatusRelays input with the given relay states."""
        return inputs.ModStatusRelays(module.address, states)

    async def test_get_single_relay_publishes_state(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """relay/3/get requests status and publishes the state of relay 3 only."""
        states = [False] * 8
        states[2] = True
        result_input = self._make_relay_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_relays.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/3/get", "", module_with_conn, bridge)

        conn.request_status_relays.assert_awaited_once()
        mock_publish.assert_called_once_with(
            module_with_conn.prefix,
            MqttMessage("relay/3/state", "on"),
        )

    async def test_get_all_relays_publishes_eight_states(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """relay/get requests status and publishes a state message for all 8 relays."""
        result_input = self._make_relay_inp([False] * 8, module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_relays.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/get", "", module_with_conn, bridge)

        conn.request_status_relays.assert_awaited_once()
        assert mock_publish.call_count == 8

    async def test_get_all_relays_correct_payloads(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """relay/get publishes correct topic and payload for every relay."""
        states = [True, False, True, False, True, False, True, False]
        result_input = self._make_relay_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_relays.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/get", "", module_with_conn, bridge)

        assert mock_publish.call_args_list == [
            call(
                module_with_conn.prefix,
                MqttMessage(f"relay/{idx}/state", "on" if state else "off"),
            )
            for idx, state in enumerate(states, start=1)
        ]

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A relay index outside 1-8 is silently ignored."""
        conn = cast(AsyncMock, module_with_conn._device_connection)
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/9/get", "", module_with_conn, bridge)
        conn.request_status_relays.assert_not_awaited()
        mock_publish.assert_not_called()

    async def test_invalid_index_returns_early(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A non-integer relay index causes the handler to return without publishing."""
        conn = cast(AsyncMock, module_with_conn._device_connection)
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/abc/get", "", module_with_conn, bridge)
        conn.request_status_relays.assert_not_awaited()
        mock_publish.assert_not_called()

    async def test_none_result_publishes_nothing(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """When request_status_relays returns None, nothing is published."""
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.request_status_relays.return_value = None

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("relay/1/get", "", module_with_conn, bridge)
        mock_publish.assert_not_called()

    async def test_no_device_connection_returns_early(
        self, module: Device, bridge: Bridge
    ) -> None:
        """When there is no device connection, accessing it raises ValueError."""
        with pytest.raises(ValueError):
            await handle_get_command("relay/1/get", "", module, bridge)
