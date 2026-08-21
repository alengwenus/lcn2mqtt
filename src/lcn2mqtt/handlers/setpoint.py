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
def handle_setpoint_input(
    inp: inputs.ModStatusVar, module: Device, bridge: Bridge
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
        bridge.publish(
            module.prefix, MqttMessage(f"setpoint/{idx}/state", str(value_unit))
        )
    if variable.update_locked(inp.value.is_locked_regulator()):
        bridge.publish(
            module.prefix,
            MqttMessage(
                f"setpoint/{idx}/locked",
                "on" if inp.value.is_locked_regulator() else "off",
            ),
        )


@mqtt_handler(
    "setpoint/+/set", "setpoint/+/shift", "setpoint/+/offset", "setpoint/+/lock"
)
async def handle_setpoint_change(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change a setpoint value."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        action = parts[2]
        variable = lcn_defs.Var.set_point_id_to_var(idx - 1)
    except ValueError:
        _LOG.warning("Received command for invalid setpoint index %d", idx)
        return

    serial = device_connection.serials.software_serial

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
        await device_connection.var_abs(variable, value, unit, serial)
    elif action == "shift":
        # shift current setpoint
        await device_connection.var_rel(
            variable, value, unit, lcn_defs.RelVarRef.CURRENT, serial
        )
    elif action == "offset":
        # shift programmed setpoint
        await device_connection.var_rel(
            variable, value, unit, lcn_defs.RelVarRef.PROG, serial
        )
    elif action == "lock":
        # lock regulator to value
        await device_connection.lock_regulator(idx - 1, True, value)


@mqtt_handler("setpoint/+/state", "setpoint/+/locked")
async def handle_retained_setpoint_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a setpoint."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        action = parts[2]
    except ValueError:
        return

    setpoint_obj = getattr(module, f"setpoint{idx}")
    if setpoint_obj is None:
        return

    if action == "state":
        try:
            var_value = lcn_defs.VarValue.from_var_unit(
                float(payload), setpoint_obj.unit, True
            )
            setpoint_obj.value = var_value.to_native()
        except (ValueError, TypeError):
            _LOG.warning("Invalid setpoint state payload %r", payload)
            return
    elif action == "locked":
        if payload.lower() not in ("on", "off"):
            _LOG.warning("Invalid setpoint locked payload %r", payload)
            return
        setpoint_obj.locked = payload.lower() == "on"


@mqtt_handler("setpoint/+/get")
async def handle_setpoint_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current setpoint values for a setpoint."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= len(lcn_defs.Var.set_points()):
        return
    variable = lcn_defs.Var.set_point_id_to_var(idx - 1)
    result_input = await device_connection.request_status_variable(variable)
    if result_input is None:
        return
    setpoint_obj = getattr(module, f"setpoint{idx}", None)
    if setpoint_obj is None:
        return
    unit = setpoint_obj.unit
    value_unit = result_input.value.to_var_unit(unit, is_lockable_regulator_source=True)
    bridge.publish(module.prefix, MqttMessage(f"setpoint/{idx}/state", str(value_unit)))
    bridge.publish(
        module.prefix,
        MqttMessage(
            f"setpoint/{idx}/locked",
            "on" if result_input.value.is_locked_regulator() else "off",
        ),
    )
