"""Tests for the binary sensor input handler."""

from __future__ import annotations

import logging

import pytest
from pypck import inputs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.binsensor import handle_binsensor_input, handle_retained_state
from lcn2mqtt.models.device import Device


class TestHandleBinsensorInput:
    """Tests for handle_binsensor_input."""

    async def test_all_sensors_reported_on_first_call(self, module: Device) -> None:
        """All 8 sensors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusBinSensors(module.address, [False] * 8)
        messages = list(handle_binsensor_input(inp, module=module))
        assert len(messages) == 8

    async def test_states_on_first_call(self, module: Device) -> None:
        """Sensor changing from unknown to True/False produces messages withcorrect payloads."""
        states = [True] * 4 + [False] * 4
        inp = inputs.ModStatusBinSensors(module.address, states)
        messages = list(handle_binsensor_input(inp, module=module))
        mapping = {True: "on", False: "off"}
        assert all(
            message.topic == f"binsensor/{idx + 1}/state"
            and message.payload == mapping[state]
            for idx, (state, message) in enumerate(zip(states, messages))
        )

    async def test_only_changed_sensors_produce_messages(self, module: Device) -> None:
        """Only the sensors whose state changed produce a message."""
        # First call: set initial states
        list(
            handle_binsensor_input(
                inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6),
                module=module,
            )
        )
        # Second call: only sensor 2 changes
        messages = list(
            handle_binsensor_input(
                inputs.ModStatusBinSensors(module.address, [True, True] + [False] * 6),
                module=module,
            )
        )
        assert len(messages) == 1
        assert messages[0].topic == "binsensor/2/state"
        assert messages[0].payload == "on"

    async def test_no_change_produces_no_messages(self, module: Device) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6)
        list(handle_binsensor_input(inp, module=module))
        messages = list(handle_binsensor_input(inp, module=module))
        assert messages == []


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
