"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from itertools import chain
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
def handle_threshold_input(
    inp: inputs.ModStatusVar, module: Device, bridge: Bridge
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
        bridge.publish(
            module.prefix,
            MqttMessage(f"threshold/{register}/{idx}/state", str(value_unit)),
        )
    if threshold.update_locked(inp.value.is_locked_threshold()):
        bridge.publish(
            module.prefix,
            MqttMessage(
                f"threshold/{register}/{idx}/locked",
                "on" if inp.value.is_locked_threshold() else "off",
            ),
        )


@mqtt_handler(
    "threshold/+/set",
    "threshold/+/shift",
    "threshold/+/offset",
    "threshold/+/lock",
)
async def handle_threshold_change(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change a threshold value."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        register = int(parts[1])
        idx = int(parts[2])
        action = parts[3]
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


@mqtt_handler("threshold/+/+/state", "threshold/+/+/locked")
async def handle_retained_threshold_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a threshold."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        register = int(parts[1])
        idx = int(parts[2])
        action = parts[3]
        threshold_obj = getattr(module, f"threshold{register}{idx}")
    except ValueError:
        return

    if threshold_obj is None:
        return

    if action == "state":
        try:
            var_value = lcn_defs.VarValue.from_var_unit(
                float(payload), threshold_obj.unit, True
            )
            threshold_obj.value = var_value.to_native()
        except (ValueError, TypeError):
            _LOG.warning("Invalid threshold state payload %r", payload)
            return
    elif action == "locked":
        if payload.lower() not in ("on", "off"):
            _LOG.warning("Invalid threshold locked payload %r", payload)
            return
        threshold_obj.locked = payload.lower() == "on"


@mqtt_handler("threshold/+/get")
async def handle_threshold_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current threshold values for a register."""
    device_connection = module.device_connection
    serial = device_connection.serials.software_serial
    thresholds_list = (
        lcn_defs.Var.thresholds_old()
        if serial < 0x170206
        else lcn_defs.Var.thresholds_new()
    )
    parts = subtopic.split("/")
    try:
        register = int(parts[1])
        if not 1 <= register <= len(thresholds_list):
            return
        # requesting any threshold in a register triggers LCN to respond for all indices
        variable = thresholds_list[register - 1][0]
    except (ValueError, IndexError):
        return
    await device_connection.request_status_variable(variable)
