"""Tests for the variable, setpoint, and threshold handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.setpoint import (
    handle_retained_setpoint_state,
    handle_setpoint_change,
    handle_setpoint_get_command,
    handle_setpoint_input,
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


class TestHandleSetpointInput:
    """Tests for the ModStatusVar setpoint input handler."""

    async def test_new_value_produces_state_message(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A new setpoint value publishes a state message."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        with patch.object(bridge, "publish") as mock_publish:
            handle_setpoint_input(inp, module=module, bridge=bridge)

        assert mock_publish.call_count == 2

    async def test_locked_value_produces_locked_message(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A locked setpoint value publishes a locked message with payload 'on'."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_LOCKED)
        with patch.object(bridge, "publish") as mock_publish:
            handle_setpoint_input(inp, module=module, bridge=bridge)

        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("setpoint/1/locked", "on", delay=0.0),
        )

    async def test_unlocked_value_produces_locked_off_message(
        self, module: Device, bridge: Bridge
    ) -> None:
        """After being locked, an unlocked value publishes locked='off'."""
        # First set as locked so the unlock triggers a change
        module.setpoint1.locked = True
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        with patch.object(bridge, "publish") as mock_publish:
            handle_setpoint_input(inp, module=module, bridge=bridge)

        mock_publish.assert_any_call(
            module.prefix,
            MqttMessage("setpoint/1/locked", "off", delay=0.0),
        )

    async def test_non_setpoint_type_returns_empty(
        self, module: Device, bridge: Bridge
    ) -> None:
        """A plain variable var type is ignored by the setpoint handler."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        with patch.object(bridge, "publish") as mock_publish:
            handle_setpoint_input(inp, module=module, bridge=bridge)
        mock_publish.assert_not_called()


class TestHandleSetpointChange:
    """Tests for the setpoint set/shift/offset/lock MQTT command handler."""

    async def test_set_action_calls_var_abs(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'set' calls var_abs."""
        await handle_setpoint_change("setpoint/1/set", "1000", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_abs.assert_awaited_once_with(
            lcn_defs.Var.R1VARSETPOINT,
            1000,
            lcn_defs.VarUnit.NATIVE,
            conn.serials.software_serial,
        )

    async def test_shift_action_calls_var_rel_current(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'shift' calls var_rel with RelVarRef.CURRENT."""
        await handle_setpoint_change(
            "setpoint/1/shift", "1000", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_rel.assert_awaited_once_with(
            lcn_defs.Var.R1VARSETPOINT,
            1000,
            lcn_defs.VarUnit.NATIVE,
            lcn_defs.RelVarRef.CURRENT,
            conn.serials.software_serial,
        )

    async def test_offset_action_calls_var_rel_prog(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'offset' calls var_rel with RelVarRef.PROG."""
        await handle_setpoint_change(
            "setpoint/1/offset", "1000", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.var_rel.assert_awaited_once_with(
            lcn_defs.Var.R1VARSETPOINT,
            1000,
            lcn_defs.VarUnit.NATIVE,
            lcn_defs.RelVarRef.PROG,
            conn.serials.software_serial,
        )

    @pytest.mark.parametrize(
        "payload,expected_locked",
        [
            ("on", True),
            ("off", False),
        ],
    )
    async def test_lock_action_calls_lock_regulator(
        self,
        module_with_conn: Device,
        config: AppConfig,
        payload: str,
        expected_locked: bool,
    ) -> None:
        """Action 'lock' calls lock_regulator with the expected locked state."""
        await handle_setpoint_change(
            "setpoint/1/lock", payload, module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.lock_regulator.assert_awaited_once_with(0, expected_locked)

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric payload for set/shift/offset logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_setpoint_change(
                "setpoint/1/set", "notanumber", module_with_conn, config
            )
        conn = cast(AsyncMock, module_with_conn.device_connection)
        assert conn is not None
        conn.var_abs.assert_not_awaited()
        assert any("setpoint" in record.message.lower() for record in caplog.records)


class TestHandleRetainedSetpointState:
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
        """Sending a retained state command updates the module's setpoint state."""
        module.setpoint1.unit = unit.name.lower()  # type: ignore[assignment]
        assert module.setpoint1.value is None
        await handle_retained_setpoint_state(
            "setpoint/1/state", payload, module, bridge
        )
        expected_var_value = lcn_defs.VarValue.from_var_unit(expected_state, unit, True)
        assert module.setpoint1.value == expected_var_value.to_native()

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
            await handle_retained_setpoint_state(
                "setpoint/1/state", payload, module, bridge
            )
        assert any(
            "Invalid setpoint state payload" in record.message
            for record in caplog.records
        )


class TestHandleRetainedSetpointLocked:
    """Tests for the retained locked state MQTT command handler."""

    @pytest.mark.parametrize(
        "payload,expected_state",
        [
            ("on", True),
            ("off", False),
        ],
    )
    async def test_retained_locked_updates_module(
        self,
        module: Device,
        bridge: Bridge,
        payload: str,
        expected_state: bool,
    ) -> None:
        """Sending a retained locked command updates the module's setpoint locked state."""
        assert module.setpoint1.locked is None
        await handle_retained_setpoint_state(
            "setpoint/1/locked", payload, module, bridge
        )
        assert module.setpoint1.locked == expected_state

    async def test_invalid_payload_logs_warning(
        self,
        module: Device,
        bridge: Bridge,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_setpoint_state(
                "setpoint/1/locked", "unknown", module, bridge
            )
        assert any(
            "Invalid setpoint locked payload" in record.message
            for record in caplog.records
        )


class TestHandleSetpointGetCommand:
    """Tests for the setpoint/+/get MQTT command handler."""

    async def test_get_publishes_state_and_locked(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A valid get command requests status and publishes state and locked messages."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_variable.return_value = inputs.ModStatusVar(
            module_with_conn.address, SETPOINT1, NATIVE_1000
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_setpoint_get_command(
                "setpoint/1/get", "", module_with_conn, bridge
            )

        conn.request_status_variable.assert_awaited_once_with(SETPOINT1)
        mock_publish.assert_any_call(
            module_with_conn.prefix,
            MqttMessage("setpoint/1/state", "1000"),
        )
        mock_publish.assert_any_call(
            module_with_conn.prefix,
            MqttMessage("setpoint/1/locked", "off"),
        )

    async def test_get_locked_setpoint_publishes_locked_on(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """A locked setpoint get publishes locked='on'."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_variable.return_value = inputs.ModStatusVar(
            module_with_conn.address, SETPOINT1, NATIVE_LOCKED
        )

        with patch.object(bridge, "publish") as mock_publish:
            await handle_setpoint_get_command(
                "setpoint/1/get", "", module_with_conn, bridge
            )

        mock_publish.assert_any_call(
            module_with_conn.prefix,
            MqttMessage("setpoint/1/locked", "on"),
        )

    async def test_get_with_none_result_does_not_publish(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """If request_status_variable returns None, nothing is published."""
        conn = cast(AsyncMock, module_with_conn.device_connection)
        conn.request_status_variable.return_value = None

        with patch.object(bridge, "publish") as mock_publish:
            await handle_setpoint_get_command(
                "setpoint/1/get", "", module_with_conn, bridge
            )

        mock_publish.assert_not_called()

    async def test_get_with_out_of_range_idx_does_nothing(
        self, module_with_conn: Device, bridge: Bridge
    ) -> None:
        """An out-of-range setpoint index does nothing."""
        conn = cast(AsyncMock, module_with_conn.device_connection)

        with patch.object(bridge, "publish") as mock_publish:
            await handle_setpoint_get_command(
                "setpoint/999/get", "", module_with_conn, bridge
            )

        conn.request_status_variable.assert_not_awaited()
        mock_publish.assert_not_called()
