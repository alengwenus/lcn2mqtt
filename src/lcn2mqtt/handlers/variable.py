"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from itertools import chain
from pypck import inputs, lcn_defs
from pypck.device import DeviceConnection

from ..module import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class VariableHandler:
    """Handles status updates for LCN variables."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusVar, module: Module, prefix: str
    ) -> None:
        """Handle a variable status input, update the module state, and publish any changes."""
        if inp.var not in lcn_defs.Var.variables():
            return
        idx = lcn_defs.Var.to_var_id(inp.var) + 1
        variable = getattr(module, f"variable{idx}", None)
        if variable is None:
            _LOG.warning("Received variable input for invalid variable index %d", idx)
            return
        unit = variable.unit
        value_unit = inp.value.to_var_unit(unit)
        if variable.update_value(int(inp.value.to_native())):
            await self._publish(f"{prefix}/variable/{idx}/state", value_unit)

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
        module: Module,
    ) -> None:
        """Handle a command to change a variable value."""
        if handler != "variable":
            return
        if len(parts) < 2:  # /<idx>/set
            return
        try:
            idx = int(parts[0])
            action = parts[1]
            variable = lcn_defs.Var.var_id_to_var(idx - 1)
        except ValueError:
            return

        serial = device_connection.serials.software_serial
        if serial < 0x170206:
            variables = lcn_defs.Var.variables_old()
        else:
            variables = lcn_defs.Var.variables_new()
        if variable not in variables:
            _LOG.warning("Received command for invalid variable index %d", idx)
            return

        if action == "state":
            return

        try:
            value = float(payload)
        except ValueError:
            _LOG.warning("Invalid variable payload %r", payload)
            return

        unit = getattr(module, f"variable{idx}").unit

        if action == "set":
            await device_connection.var_abs(variable, value, unit, serial)
        elif action == "shift":
            await device_connection.var_rel(
                variable, value, unit, lcn_defs.RelVarRef.CURRENT, serial
            )


class SetpointHandler:
    """Handles status updates for LCN setpoints."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusVar, module: Module, prefix: str
    ) -> None:
        """Handle a setpoint status input, update the module state, and publish any changes."""
        if inp.var not in lcn_defs.Var.set_points():
            return
        idx = lcn_defs.Var.to_set_point_id(inp.var) + 1
        variable = getattr(module, f"setpoint{idx}", None)
        if variable is None:
            _LOG.warning("Received variable input for invalid setpoint index %d", idx)
            return
        unit = variable.unit
        value_unit = inp.value.to_var_unit(unit, is_lockable_regulator_source=True)

        if variable.update_value(int(inp.value.to_native())):
            await self._publish(f"{prefix}/setpoint/{idx}/state", value_unit)
        if variable.update_locked(inp.value.is_locked_regulator()):
            await self._publish(
                f"{prefix}/setpoint/{idx}/locked",
                "on" if inp.value.is_locked_regulator() else "off",
            )

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
        module: Module,
    ) -> None:
        """Handle a command to change a setpoint value."""
        if handler != "setpoint":
            return
        if len(parts) < 2:  # /<idx>/set
            return
        try:
            idx = int(parts[0])
            action = parts[1]
            variable = lcn_defs.Var.set_point_id_to_var(idx - 1)
        except ValueError:
            _LOG.warning("Received command for invalid setpoint index %d", idx)
            return

        if action in ["state", "locked"]:
            return

        if action == "lock" and payload.lower() in ("on", "off"):
            # lock or unlock regulator
            await device_connection.lock_regulator(idx - 1, payload.lower() == "on")
            return

        try:
            value = float(payload)
        except ValueError:
            _LOG.warning("Invalid setpoint payload %r", payload)
            return

        unit = getattr(module, f"setpoint{idx}").unit

        if action == "set":
            await device_connection.var_abs(variable, value, unit)
        elif action == "shift":
            # shift current setpoint
            await device_connection.var_rel(
                variable, value, unit, lcn_defs.RelVarRef.CURRENT
            )
        elif action == "offset":
            # shift programmed setpoint
            await device_connection.var_rel(
                variable, value, unit, lcn_defs.RelVarRef.PROG
            )
        elif action == "lock":
            # lock regulator to value
            await device_connection.lock_regulator(idx - 1, True, value)


class ThresholdHandler:
    """Handles status updates for LCN thresholds."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusVar, module: Module, prefix: str
    ) -> None:
        """Handle a threshold status input, update the module state, and publish any changes."""
        if inp.var not in list(chain.from_iterable(lcn_defs.Var.thresholds())):
            return

        register = lcn_defs.Var.to_thrs_register_id(inp.var) + 1
        idx = lcn_defs.Var.to_thrs_id(inp.var) + 1
        threshold = getattr(module, f"threshold{register}{idx}", None)
        if threshold is None:
            _LOG.warning(
                "Received threshold input for invalid threshold %d-%d", register, idx
            )
            return

        # value_native = int(inp.value.to_native())
        unit = threshold.unit
        value_unit = inp.value.to_var_unit(unit, is_lockable_regulator_source=True)

        if threshold.update_value(
            int(inp.value.to_native())
        ):  # and (value_native != 0xFFFF):
            await self._publish(
                f"{prefix}/threshold/{register}/{idx}/state", value_unit
            )
        if threshold.update_locked(inp.value.is_locked_threshold()):
            await self._publish(
                f"{prefix}/threshold/{register}/{idx}/locked",
                "on" if inp.value.is_locked_threshold() else "off",
            )

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
        module: Module,
    ) -> None:
        """Handle a command to change a threshold value."""
        if handler != "threshold":
            return
        if len(parts) < 3:  # /<register>/<idx>/set
            return
        try:
            register = int(parts[0])
            idx = int(parts[1])
            action = parts[2]
            variable = lcn_defs.Var.thrs_id_to_var(register - 1, idx - 1)
        except ValueError:
            return

        serial = device_connection.serials.software_serial
        if serial < 0x170206:
            variables = list(chain.from_iterable(lcn_defs.Var.thresholds_old()))
        else:
            variables = list(chain.from_iterable(lcn_defs.Var.thresholds_new()))
        if variable not in variables:
            _LOG.warning("Received command for invalid threshold %d-%d", register, idx)
            return

        if action in ["state", "locked"]:
            return

        if action == "lock" and payload.lower() in ("on", "off"):
            # lock or unlock threshold
            states = [lcn_defs.ThresholdLockStateModifier.NOCHANGE] * 4
            states[idx - 1] = (
                lcn_defs.ThresholdLockStateModifier.ON
                if payload.lower() == "on"
                else lcn_defs.ThresholdLockStateModifier.OFF
            )
            await device_connection.lock_thresholds(register - 1, states)
            return

        try:
            value = float(payload)
        except ValueError:
            _LOG.warning("Invalid threshold payload %r", payload)
            return

        unit = getattr(module, f"threshold{register}{idx}").unit

        if action == "shift":
            await device_connection.var_rel(
                variable, value, unit, lcn_defs.RelVarRef.CURRENT, serial
            )
        elif action == "offset":
            await device_connection.var_rel(
                variable, value, unit, lcn_defs.RelVarRef.PROG, serial
            )
