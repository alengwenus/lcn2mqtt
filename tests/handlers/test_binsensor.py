"""Tests for the binary sensor input handler."""

from __future__ import annotations

from pypck import inputs

from lcn2mqtt.handlers.binsensor import handle_binsensor_input
from lcn2mqtt.models.module import Module


class TestHandleBinsensorInput:
    """Tests for handle_binsensor_input."""

    async def test_all_sensors_reported_on_first_call(self, module: Module) -> None:
        """All 8 sensors produce a message on the very first call (all were unknown)."""
        inp = inputs.ModStatusBinSensors(module.address, [False] * 8)
        messages = await handle_binsensor_input(inp, module=module)
        assert len(messages) == 8

    async def test_states_on_first_call(self, module: Module) -> None:
        """Sensor changing from unknown to True/False produces messages withcorrect payloads."""
        states = [True] * 4 + [False] * 4
        inp = inputs.ModStatusBinSensors(module.address, states)
        messages = await handle_binsensor_input(inp, module=module)
        mapping = {True: "on", False: "off"}
        assert all(
            message.topic == f"binsensor/{idx + 1}/state"
            and message.payload == mapping[state]
            for idx, (state, message) in enumerate(zip(states, messages))
        )

    async def test_only_changed_sensors_produce_messages(self, module: Module) -> None:
        """Only the sensors whose state changed produce a message."""
        # First call: set initial states
        await handle_binsensor_input(
            inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6),
            module=module,
        )
        # Second call: only sensor 2 changes
        messages = await handle_binsensor_input(
            inputs.ModStatusBinSensors(module.address, [True, True] + [False] * 6),
            module=module,
        )
        assert len(messages) == 1
        assert messages[0].topic == "binsensor/2/state"
        assert messages[0].payload == "on"

    async def test_no_change_produces_no_messages(self, module: Module) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = inputs.ModStatusBinSensors(module.address, [True, False] + [False] * 6)
        await handle_binsensor_input(inp, module=module)
        messages = await handle_binsensor_input(inp, module=module)
        assert messages == []
