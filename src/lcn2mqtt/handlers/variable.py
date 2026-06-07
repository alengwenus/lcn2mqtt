"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs
from pypck.device import DeviceConnection

from ..models import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

_VAR_INDEX_MAP = {
    "VAR1ORTVAR": 1,
    "VAR2ORR1VAR": 2,
    "VAR3ORR2VAR": 3,
    "VAR4": 4,
    "VAR5": 5,
    "VAR6": 6,
    "VAR7": 7,
    "VAR8": 8,
    "VAR9": 9,
    "VAR10": 10,
    "VAR11": 11,
    "VAR12": 12,
}


def _var_index(var: Any) -> int | None:
    """Convert an LCN variable identifier to a 1-based index, or return None if it can't be determined."""
    name = getattr(var, "name", "")
    if not isinstance(name, str):
        return None
    if name in _VAR_INDEX_MAP:
        return _VAR_INDEX_MAP[name]
    upper = name.upper()
    if upper.startswith("VAR"):
        try:
            return int(upper[3:])
        except ValueError:
            return None
    return None


class VariableHandler:
    """Handles status updates for LCN variables."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusVar, module: Module, prefix: str
    ) -> None:
        """Handle a variable status input, update the module state, and publish any changes."""
        if inp.var not in lcn_defs.Var.variables_new() + lcn_defs.Var.variables_old():
            return
        idx = inp.var.value + 1
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
            variable = lcn_defs.Var(idx - 1)
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

        if action == "set":
            try:
                value = float(payload)
            except ValueError:
                _LOG.warning("Invalid variable payload %r", payload)
                return

            unit = getattr(module, f"variable{idx}").unit

            await device_connection.var_abs(variable, value, unit, serial)
