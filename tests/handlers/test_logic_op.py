"""Tests for the logic operation handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, call, patch

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.logic_op import (
    handle_get_command,
    handle_input,
    handle_retained_state,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.device import Device, LogicOpState

_ALL_LEDS = [lcn_defs.LedStatus.OFF] * 12
_ALL_NONE = [lcn_defs.LogicOpStatus.NONE] * 4


def _make_logic_op_inp(
    states: list[lcn_defs.LogicOpStatus], module: Device
) -> inputs.ModStatusLedsAndLogicOps:
    """Build a ModStatusLedsAndLogicOps input with the given logic operation states."""
    return inputs.ModStatusLedsAndLogicOps(module.address, _ALL_LEDS, states)


class TestHandleLogicOpInput:
    """Tests for the ModStatusLedsAndLogicOps input handler (logic op side)."""

    async def test_all_logic_ops_reported_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """All 4 logic ops produce a message on the very first call (all were unknown)."""
        inp = _make_logic_op_inp(_ALL_NONE, module)
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(inp, module=module, bridge=bridge)
            assert mock_publish.call_count == 4

    async def test_all_logic_ops_covered_on_first_call(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Logic ops changing from unknown to states produce messages with correct payloads."""
        states = [
            lcn_defs.LogicOpStatus.NONE,
            lcn_defs.LogicOpStatus.SOME,
            lcn_defs.LogicOpStatus.ALL,
            lcn_defs.LogicOpStatus.NONE,
        ]
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(
                _make_logic_op_inp(states, module), module=module, bridge=bridge
            )

        assert mock_publish.call_args_list == [
            call(
                module.prefix,
                MqttMessage(
                    f"logic_op/{idx + 1}/state",
                    state.name.lower(),
                    delay=0.0,
                ),
            )
            for idx, state in enumerate(states)
        ]

    async def test_changed_logic_ops_produce_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Only logic ops whose state changed produce a message."""
        handle_input(
            _make_logic_op_inp(_ALL_NONE, module), module=module, bridge=bridge
        )
        states = [lcn_defs.LogicOpStatus.ALL] + [lcn_defs.LogicOpStatus.NONE] * 3
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(
                _make_logic_op_inp(states, module), module=module, bridge=bridge
            )
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1].topic == "logic_op/1/state"
            assert mock_publish.call_args[0][1].payload == "all"

    async def test_no_change_produces_no_messages(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Identical consecutive inputs yield no messages."""
        inp = _make_logic_op_inp(_ALL_NONE, module)
        handle_input(inp, module=module, bridge=bridge)
        with patch.object(bridge, "publish") as mock_publish:
            handle_input(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()


class TestHandleRetainedState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("none", LogicOpState.NONE),
            ("some", LogicOpState.SOME),
            ("all", LogicOpState.ALL),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: LogicOpState,
    ) -> None:
        """Sending a retained state command updates the module's logic op state."""
        assert module.logic_op1 is None
        await handle_retained_state("logic_op/1/state", payload, module, bridge)
        assert module.logic_op1 == expected_state

    async def test_invalid_payload_logs_warning(
        self, module: Device, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_state("logic_op/1/state", "unknown", module, bridge)
        assert any(
            "Invalid logic operation state payload" in record.message
            for record in caplog.records
        )

    async def test_out_of_range_index_returns_early(
        self, module: Device, bridge: Bridge
    ) -> None:
        """An index outside 1–4 does not update the module."""
        await handle_retained_state("logic_op/5/state", "none", module, bridge)
        assert module.logic_op1 is None

    async def test_non_integer_index_returns_early(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A non-integer index does not update the module."""
        await handle_retained_state("logic_op/abc/state", "none", module, bridge)
        assert module.logic_op1 is None

    async def test_no_retained_states_skips_update(
        self, module: Device, bridge: Bridge
    ) -> None:
        """When retained_broker_states is disabled, the handler returns immediately."""
        bridge.config.retained_broker_states = False
        await handle_retained_state("logic_op/1/state", "none", module, bridge)
        assert module.logic_op1 is None


class TestHandleGetCommand:
    """Tests for the logic operation get MQTT command handler."""

    async def test_get_single_logic_op_publishes_state(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """logic_op/2/get requests status and publishes the state of logic op 2 only."""
        states = [
            lcn_defs.LogicOpStatus.NONE,
            lcn_defs.LogicOpStatus.ALL,
            lcn_defs.LogicOpStatus.NONE,
            lcn_defs.LogicOpStatus.NONE,
        ]
        result_input = _make_logic_op_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("logic_op/2/get", "", module_with_conn, bridge)

        conn.request_status_leds_and_logic_ops.assert_awaited_once()
        mock_publish.assert_called_once_with(
            module_with_conn.prefix,
            MqttMessage("logic_op/2/state", "all"),
        )

    async def test_get_all_logic_ops_publishes_four_states(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """logic_op/get requests status and publishes a state message for all 4 logic ops."""
        result_input = _make_logic_op_inp(list(_ALL_NONE), module_with_conn)
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("logic_op/get", "", module_with_conn, bridge)

        conn.request_status_leds_and_logic_ops.assert_awaited_once()
        assert mock_publish.call_count == 4

    async def test_get_all_logic_ops_correct_payloads(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """logic_op/get publishes correct topic and payload for every logic op."""
        states = [
            lcn_defs.LogicOpStatus.NONE,
            lcn_defs.LogicOpStatus.SOME,
            lcn_defs.LogicOpStatus.ALL,
            lcn_defs.LogicOpStatus.NONE,
        ]
        result_input = _make_logic_op_inp(states, module_with_conn)
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_leds_and_logic_ops.return_value = result_input

        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command("logic_op/get", "", module_with_conn, bridge)

        assert mock_publish.call_args_list == [
            call(
                module_with_conn.prefix,
                MqttMessage(f"logic_op/{idx + 1}/state", state.name.lower()),
            )
            for idx, state in enumerate(states)
        ]

    @pytest.mark.parametrize(
        "subtopic, payload",
        [
            ("logic_op/5/get", "none"),  # invalid index
            ("logic_op/abc/get", "none"),  # non-integer index
            ("logic_op/1/get", None),  # no state returned (None)
        ],
    )
    async def test_invalid_parameters_return_early(
        self,
        module_with_conn: Device,
        bridge: Bridge,
        subtopic: str,
        payload: str | None,
    ) -> None:
        """Invalid parameters and return values are ignored."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_leds_and_logic_ops.return_value = payload
        with patch.object(bridge, "publish") as mock_publish:
            await handle_get_command(subtopic, "", module_with_conn, bridge)
        if payload is not None:
            conn.request_status_leds_and_logic_ops.assert_not_awaited()
        else:
            conn.request_status_leds_and_logic_ops.assert_awaited_once()
        mock_publish.assert_not_called()
