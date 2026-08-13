"""Tests for the binary sensor input handler."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, call, patch

import pytest
from pypck import inputs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.binsensor import (
    handle_binsensor_input,
    handle_get_command,
    handle_retained_state,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.device import Device


class TestHandleBinsensorInput:
    """Tests for handle_binsensor_input."""

    async def test_all_sensors_reported_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """All 8 sensors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusBinSensors(module.address, [False] * 8)
        with patch.object(bridge, "publish") as mock_publish:
            handle_binsensor_input(inp, module=module, bridge=bridge)

        assert mock_publish.call_count == 8

    async def test_states_on_first_call(self, module: Device, bridge: Bridge) -> None:
        """Sensor changing from unknown to True/False produces messages withcorrect payloads."""
        states = [True] * 4 + [False] * 4
        inp = inputs.ModStatusBinSensors(module.address, states)
        with patch.object(bridge, "publish") as mock_publish:
            handle_binsensor_input(inp, module=module, bridge=bridge)

        assert mock_publish.call_args_list == [
            call(
                module.prefix,
                MqttMessage(
                    f"binsensor/{idx + 1}/state",
                    "on" if states[idx] else "off",
                    delay=0.0,
                ),
            )
            for idx in range(8)
        ]

    async def test_only_changed_sensors_produce_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Only the sensors whose state changed produce a message."""
        # First call: set initial states
        handle_binsensor_input(
            inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6),
            module=module,
            bridge=bridge,
        )
        # Second call: only sensor 2 changes
        with patch.object(bridge, "publish") as mock_publish:
            handle_binsensor_input(
                inputs.ModStatusBinSensors(module.address, [True, True] + [False] * 6),
                module=module,
                bridge=bridge,
            )
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1].topic == "binsensor/2/state"
            assert mock_publish.call_args[0][1].payload == "on"

    async def test_no_change_produces_no_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6)
        handle_binsensor_input(inp, module=module, bridge=bridge)
        with patch.object(bridge, "publish") as mock_publish:
            handle_binsensor_input(inp, module=module, bridge=bridge)
            mock_publish.assert_not_called()


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("on", True),
            ("off", False),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: bool,
    ) -> None:
        """Sending a retained state command updates the module's binsensor state."""
        assert module.binsensor1 is None
        await handle_retained_state("binsensor/1/state", payload, module, bridge)
        assert module.binsensor1 == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("binsensor/1/state", "unknown", module, bridge)
        assert any(
            "Invalid binary sensor state payload" in record.message
            for record in caplog.records
        )


class TestHandleGetCommand:
    """Tests for the binsensor/+/get and binsensor/get MQTT command handler."""

    def _make_inp(
        self, states: list[bool], module: Device
    ) -> inputs.ModStatusBinSensors:
        return inputs.ModStatusBinSensors(module.address, states)

    async def test_get_single_sensor_on(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """binsensor/3/get publishes 'on' when sensor 3 is active."""

        states = [False] * 8
        states[2] = True
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_binary_sensors.return_value = self._make_inp(
            states, module_with_conn
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/3/get", "", module_with_conn, bridge)

        conn.request_status_binary_sensors.assert_awaited_once()
        mock_publish.assert_called_once_with(
            module_with_conn.prefix,
            MqttMessage("binsensor/3/state", "on"),
        )

    async def test_get_all_sensors_publishes_eight_states(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """binsensor/get publishes a state message for all 8 sensors."""

        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_binary_sensors.return_value = self._make_inp(
            [False] * 8, module_with_conn
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/get", "", module_with_conn, bridge)

        conn.request_status_binary_sensors.assert_awaited_once()
        assert mock_publish.call_count == 8

    async def test_get_all_sensors_correct_payloads(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """binsensor/get publishes correct topic and payload for every sensor."""
        states = [True, False, True, False, True, False, True, False]
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_binary_sensors.return_value = self._make_inp(
            states, module_with_conn
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/get", "", module_with_conn, bridge)

        assert mock_publish.call_args_list == [
            call(
                module_with_conn.prefix,
                MqttMessage(f"binsensor/{i}/state", "on" if s else "off"),
            )
            for i, s in enumerate(states, start=1)
        ]

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A sensor index outside 1-8 is silently ignored."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/9/get", "", module_with_conn, bridge)
        conn.request_status_binary_sensors.assert_not_awaited()
        mock_publish.assert_not_called()

    async def test_invalid_index_returns_early(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A non-integer sensor index returns early without publishing."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/abc/get", "", module_with_conn, bridge)
        conn.request_status_binary_sensors.assert_not_awaited()
        mock_publish.assert_not_called()

    async def test_none_result_publishes_nothing(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """When request_status_binary_sensors returns None, nothing is published."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_binary_sensors.return_value = None

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("binsensor/1/get", "", module_with_conn, bridge)
        mock_publish.assert_not_called()

    async def test_no_device_connection_raises(
        self, module: Device, bridge: Bridge
    ) -> None:
        """When there is no device connection, ValueError is raised."""
        with pytest.raises(ValueError):
            await handle_get_command("binsensor/1/get", "", module, bridge)
