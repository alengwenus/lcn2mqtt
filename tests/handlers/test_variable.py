"""Tests for the variable, setpoint, and threshold handlers."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pypck import inputs, lcn_defs

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.handlers.variable import (
    handle_retained_setpoint_state,
    handle_retained_threshold_state,
    handle_retained_variable_state,
    handle_setpoint_change,
    handle_setpoint_input,
    handle_threshold_change,
    handle_threshold_input,
    handle_variable_change,
    handle_variable_input,
)
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device

# Convenience helpers
VAR1 = lcn_defs.Var.var_id_to_var(0)  # VAR1ORTVAR → variable1
SETPOINT1 = lcn_defs.Var.set_point_id_to_var(0)  # R1VARSETPOINT → setpoint1
THRESHOLD11 = lcn_defs.Var.thrs_id_to_var(0, 0)  # THRS1 → threshold11

NATIVE_1000 = lcn_defs.VarValue.from_native(1000)
NATIVE_LOCKED = lcn_defs.VarValue.from_native(0x8000 + 500)  # locked flag set


# ---------------------------------------------------------------------------
# Variable handler
# ---------------------------------------------------------------------------


class TestHandleVariableInput:
    """Tests for the ModStatusVar variable input handler."""

    async def test_new_value_produces_state_message(self, module: Device) -> None:
        """A new variable value publishes a state message."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        messages = list(handle_variable_input(inp, module=module))
        assert any(message.topic == "variable/1/state" for message in messages)

    async def test_unchanged_value_produces_no_message(self, module: Device) -> None:
        """Identical consecutive values yield no messages."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        list(handle_variable_input(inp, module=module))
        messages = list(handle_variable_input(inp, module=module))
        assert messages == []

    async def test_non_variable_type_returns_empty(self, module: Device) -> None:
        """A setpoint var type is ignored by the variable handler."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        messages = list(handle_variable_input(inp, module=module))
        assert messages == []


class TestHandleVariableChange:
    """Tests for the variable set/shift MQTT command handler."""

    async def test_set_action_calls_var_abs(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'set' calls var_abs on the device connection."""
        await handle_variable_change("variable/1/set", "1000", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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


# ---------------------------------------------------------------------------
# Setpoint handler
# ---------------------------------------------------------------------------


class TestHandleSetpointInput:
    """Tests for the ModStatusVar setpoint input handler."""

    async def test_new_value_produces_state_message(self, module: Device) -> None:
        """A new setpoint value publishes a state message."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        messages = list(handle_setpoint_input(inp, module=module))
        assert any(message.topic == "setpoint/1/state" for message in messages)

    async def test_locked_value_produces_locked_message(self, module: Device) -> None:
        """A locked setpoint value publishes a locked message with payload 'on'."""
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_LOCKED)
        messages = list(handle_setpoint_input(inp, module=module))
        locked_msg = next(
            (message for message in messages if message.topic == "setpoint/1/locked"),
            None,
        )
        assert locked_msg is not None
        assert locked_msg.payload == "on"

    async def test_unlocked_value_produces_locked_off_message(
        self, module: Device
    ) -> None:
        """After being locked, an unlocked value publishes locked='off'."""
        # First set as locked so the unlock triggers a change
        module.setpoint1.locked = True
        inp = inputs.ModStatusVar(module.address, SETPOINT1, NATIVE_1000)
        messages = list(handle_setpoint_input(inp, module=module))
        locked_msg = next(
            (message for message in messages if message.topic == "setpoint/1/locked"),
            None,
        )
        assert locked_msg is not None
        assert locked_msg.payload == "off"

    async def test_non_setpoint_type_returns_empty(self, module: Device) -> None:
        """A plain variable var type is ignored by the setpoint handler."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        messages = list(handle_setpoint_input(inp, module=module))
        assert messages == []


class TestHandleSetpointChange:
    """Tests for the setpoint set/shift/offset/lock MQTT command handler."""

    async def test_set_action_calls_var_abs(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'set' calls var_abs."""
        await handle_setpoint_change("setpoint/1/set", "1000", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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
        conn = cast(AsyncMock, module_with_conn._device_connection)
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


# ---------------------------------------------------------------------------
# Threshold input handler
# ---------------------------------------------------------------------------


class TestHandleThresholdInput:
    """Tests for the ModStatusVar threshold input handler."""

    async def test_new_value_produces_state_message(self, module: Device) -> None:
        """A new threshold value publishes a state message."""
        inp = inputs.ModStatusVar(module.address, THRESHOLD11, NATIVE_1000)
        messages = list(handle_threshold_input(inp, module=module))
        assert any(m.topic == "threshold/1/1/state" for m in messages)

    async def test_locked_threshold_produces_locked_on_message(
        self, module: Device
    ) -> None:
        """A locked threshold publishes locked='on'."""
        inp = inputs.ModStatusVar(module.address, THRESHOLD11, NATIVE_LOCKED)
        messages = list(handle_threshold_input(inp, module=module))
        locked_msg = next(
            (
                message
                for message in messages
                if message.topic == "threshold/1/1/locked"
            ),
            None,
        )
        assert locked_msg is not None
        assert locked_msg.payload == "on"

    async def test_unlocked_threshold_produces_locked_off_message(
        self, module: Device
    ) -> None:
        """After being locked, an unlocked threshold publishes locked='off'."""
        # First set as locked so the unlock triggers a change
        module.threshold11.locked = True
        inp = inputs.ModStatusVar(module.address, THRESHOLD11, NATIVE_1000)
        messages = list(handle_threshold_input(inp, module=module))
        locked_msg = next(
            (
                message
                for message in messages
                if message.topic == "threshold/1/1/locked"
            ),
            None,
        )
        assert locked_msg is not None
        assert locked_msg.payload == "off"

    async def test_non_threshold_type_returns_empty(self, module: Device) -> None:
        """A plain variable var type is ignored by the threshold handler."""
        inp = inputs.ModStatusVar(module.address, VAR1, NATIVE_1000)
        messages = list(handle_threshold_input(inp, module=module))
        assert messages == []


class TestHandleThresholdChange:
    """Tests for the threshold set/shift/offset/lock MQTT command handler."""

    async def test_shift_action_calls_var_rel_current(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'shift' calls var_rel with RelVarRef.CURRENT."""
        await handle_threshold_change(
            "threshold/1/1/shift", "1000", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.var_rel.assert_awaited_once_with(
            lcn_defs.Var.THRS1,
            1000,
            lcn_defs.VarUnit.NATIVE,
            lcn_defs.RelVarRef.CURRENT,
            conn.serials.software_serial,
        )

    async def test_offset_action_calls_var_rel_prog(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Action 'offset' calls var_rel with RelVarRef.PROG."""
        await handle_threshold_change(
            "threshold/1/1/offset", "1000", module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.var_rel.assert_awaited_once_with(
            lcn_defs.Var.THRS1,
            1000,
            lcn_defs.VarUnit.NATIVE,
            lcn_defs.RelVarRef.PROG,
            conn.serials.software_serial,
        )

    @pytest.mark.parametrize(
        "payload,expected_locked",
        [
            ("on", lcn_defs.ThresholdLockStateModifier.ON),
            ("off", lcn_defs.ThresholdLockStateModifier.OFF),
        ],
    )
    async def test_lock_action_calls_lock_thresholds(
        self,
        module_with_conn: Device,
        config: AppConfig,
        payload: str,
        expected_locked: lcn_defs.ThresholdLockStateModifier,
    ) -> None:
        """Action 'lock' calls lock_thresholds with the expected locked state."""
        await handle_threshold_change(
            "threshold/1/1/lock", payload, module_with_conn, config
        )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.lock_thresholds.assert_awaited_once_with(
            0, [expected_locked] + [lcn_defs.ThresholdLockStateModifier.NOCHANGE] * 3
        )

    async def test_invalid_payload_logs_warning(
        self,
        module_with_conn: Device,
        config: AppConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A non-numeric payload for shift/offset logs a warning."""
        with caplog.at_level(logging.WARNING):
            await handle_threshold_change(
                "threshold/1/1/shift", "bad", module_with_conn, config
            )
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.var_rel.assert_not_awaited()
        assert any("threshold" in record.message.lower() for record in caplog.records)


class TestHandleRetainedThresholdState:
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
        """Sending a retained state command updates the module's threshold state."""
        module.threshold11.unit = unit.name.lower()  # type: ignore[assignment]
        assert module.threshold11.value is None
        await handle_retained_threshold_state(
            "threshold/1/1/state", payload, module, bridge
        )
        expected_var_value = lcn_defs.VarValue.from_var_unit(expected_state, unit, True)
        assert module.threshold11.value == expected_var_value.to_native()

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
            await handle_retained_threshold_state(
                "threshold/1/1/state", payload, module, bridge
            )
        assert any(
            "Invalid threshold state payload" in record.message
            for record in caplog.records
        )


class TestHandleRetainedThresholdLocked:
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
        """Sending a retained locked command updates the module's threshold locked state."""
        assert module.threshold11.locked is None
        await handle_retained_threshold_state(
            "threshold/1/1/locked", payload, module, bridge
        )
        assert module.threshold11.locked == expected_state

    async def test_invalid_payload_logs_warning(
        self,
        module: Device,
        bridge: Bridge,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unknown payload logs a warning and does not update the module."""
        with caplog.at_level(logging.WARNING):
            await handle_retained_threshold_state(
                "threshold/1/1/locked", "unknown", module, bridge
            )
        assert any(
            "Invalid threshold locked payload" in record.message
            for record in caplog.records
        )
