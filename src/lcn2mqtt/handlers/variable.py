"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusVar)
def handle_variable_input(
    inp: inputs.ModStatusVar, module: Device, bridge: Bridge
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
        bridge.publish(
            module.prefix, MqttMessage(f"variable/{idx}/state", str(value_unit))
        )


@mqtt_handler("variable/+/set", "variable/+/shift")
async def handle_variable_change(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change a variable value."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        action = parts[2]
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


@mqtt_handler("variable/+/state")
async def handle_retained_variable_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a variable."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return

    variable_obj = getattr(module, f"variable{idx}")
    if variable_obj is None:
        return

    try:
        var_value = lcn_defs.VarValue.from_var_unit(
            float(payload), variable_obj.unit, True
        )
        variable_obj.value = var_value.to_native()
    except (ValueError, TypeError):
        _LOG.warning("Invalid variable state payload %r", payload)
        return


@mqtt_handler("variable/+/get")
async def handle_variable_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current variable values for a variable."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= len(lcn_defs.Var.variables()):
        return
    variable = lcn_defs.Var.var_id_to_var(idx - 1)
    result_input = await device_connection.request_status_variable(variable)
    if result_input is None:
        return
    variable_obj = getattr(module, f"variable{idx}", None)
    if variable_obj is None:
        return
    unit = variable_obj.unit
    value_unit = result_input.value.to_var_unit(unit)
    bridge.publish(module.prefix, MqttMessage(f"variable/{idx}/state", str(value_unit)))
