"""Tests for the binary sensor input handler."""

from __future__ import annotations

import logging
from unittest.mock import call, patch

import pytest
from pypck import inputs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.binsensor import handle_binsensor_input, handle_retained_state
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
