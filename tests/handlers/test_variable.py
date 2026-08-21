"""Tests for the variable, setpoint, and threshold handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.variable import (
    handle_retained_variable_state,
    handle_variable_change,
    handle_variable_get_command,
    handle_variable_input,
)
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device

# Convenience helpers
VAR1 = lcn_defs.Var.var_id_to_var(0)  # VAR1ORTVAR → variable1
SETPOINT1 = lcn_defs.Var.set_point_id_to_var(0)  # R1VARSETPOINT → setpoint1
THRESHOLD11 = lcn_defs.Var.thrs_id_to_var(0, 0)  # THRS1 → threshold11

NATIVE_1000 = lcn_defs.VarValue.from_native(1000)
NATIVE_LOCKED = lcn_defs.VarValue.from_native(0x8000 + 500)  # locked flag set


class TestHandleVariableInput:
    """Tests for the ModStatusVar variable input handler."""

    async def test_new_value_produces_state_message(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A new variable value publishes a state message."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        with patch.object(bridge, "publish") as mock_publish:
            handle_variable_input(inp, module=module, bridge=bridge)

        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("variable/1/state", "1000", delay=0.0),
        )

    async def test_unchanged_value_produces_no_message(
        self, module: Device, bridge: Bridge
    ) -> None:
        """Identical consecutive values yield no messages."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        handle_variable_input(inp, module=module, bridge=bridge)
        with patch.object(bridge, "publish") as mock_publish:
            handle_variable_input(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()

    async def test_non_variable_type_returns_empty(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A setpoint var type is ignored by the variable handler."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        with patch.object(bridge, "publish") as mock_publish:
            handle_variable_input(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()


class TestHandleVariableChange:
    """Tests for the variable set/shift MQTT command handler."""

    async def test_set_action_calls_var_abs(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'set' calls var_abs on the device connection."""
        await handle_variable_change("variable/1/set", "1000", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_abs.assert_awaited_once_with(
            lcn_defs.Var.VAR1,
            1000,
            lcn_defs.VarUnit.NATIVE,
            conn.serials.software_serial,
        )

    async def test_shift_action_calls_var_rel(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'shift' calls var_rel on the device connection."""
        await handle_variable_change(
            "variable/1/shift", "1000", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_rel.assert_awaited_once_with(
            lcn_defs.Var.VAR1,
            1000,
            lcn_defs.VarUnit.NATIVE,
            lcn_defs.RelVarRef.CURRENT,
            conn.serials.software_serial,
        )

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric payload logs a warning and does not call the device."""
        with caplog.at_level(logging.WARNING):
            await handle_variable_change(
                "variable/1/set", "notanumber", module_with_conn, config
            )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_abs.assert_not_awaited()
        assert any("variable" in record.message.lower() for record in caplog.records)


class TestHandleRetainedVariableState:
    """Tests for the retained state MQTT command handler."""

    @pytest.mark.parametrize(
        "unit, payload,expected_state",
        [
            (lcn_defs.VarUnit.NATIVE, "0", 0),
            (lcn_defs.VarUnit.NATIVE, "50", 50),
            (lcn_defs.VarUnit.NATIVE, "100", 100),
            (lcn_defs.VarUnit.CELSIUS, "0.0", 0.0),
            (lcn_defs.VarUnit.CELSIUS, "50.5", 50.5),
            (lcn_defs.VarUnit.CELSIUS, "100.0", 100.0),
        ],
    )
    async def test_retained_state_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        unit: lcn_defs.VarUnit,
        payload: str,
        expected_state: float,
    ) -> None:
        """Sending a retained state command updates the module's variable state."""
        module.variable1.unit = unit.name.lower()  # type: ignore[assignment]
        assert module.variable1.value is None
        await handle_retained_variable_state(
            "variable/1/state", payload, module, bridge
        )
        expected_var_value = lcn_defs.VarValue.from_var_unit(expected_state, unit, True)
        assert module.variable1.value == expected_var_value.to_native()

    @pytest.mark.parametrize(
        "payload",
        [
            "unknown",
            "-150.0",
        ],
    )
    async def test_invalid_payload_logs_warning(
        self,
        module: Device,
        bridge: Bridge,
        caplog: pytest.LogCaptureFixture,
        payload: str,
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_variable_state(
                "variable/1/state", payload, module, bridge
            )
        assert any(
            "Invalid variable state payload" in record.message
            for record in caplog.records
        )


class TestHandleVariableGetCommand:
    """Tests for the variable/+/get MQTT command handler."""

    async def test_get_publishes_state(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A valid get command requests status and publishes the state."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_variable.return_value = inputs.ModStatusVar(
            module_with_conn.address, VAR1, NATIVE_1000
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_variable_get_command(
                "variable/1/get", "", module_with_conn, bridge
            )

        conn.request_status_variable.assert_awaited_once_with(VAR1)
        mock_publish.assert_called_once_with(
            module_with_conn.prefix,
            MqttMessage("variable/1/state", "1000"),
        )

    async def test_get_with_none_result_does_not_publish(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """If request_status_variable returns None, nothing is published."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_variable.return_value = None

        with patch.object(bridge, "publish") as mock_publish:
            await handle_variable_get_command(
                "variable/1/get", "", module_with_conn, bridge
            )

        mock_publish.assert_not_called()

    async def test_get_with_out_of_range_idx_does_nothing(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """An out-of-range variable index does nothing."""
        conn = cast(AsyncMock, module_with_conn.device_connection)

        with patch.object(bridge, "publish") as mock_publish:
            await handle_variable_get_command(
                "variable/999/get", "", module_with_conn, bridge
            )

        conn.request_status_variable.assert_not_awaited()
        mock_publish.assert_not_called()
