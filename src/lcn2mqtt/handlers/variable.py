"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Generator
from itertools import chain
from typing import Any

from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig

from ..models.module import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


# ---------- Variables ----------


@input_handler(inputs.ModStatusVar)
def handle_variable_input(
    inp: inputs.ModStatusVar, module: Module
) -> Generator[MqttMessage]:
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
        yield MqttMessage(f"variable/{idx}/state", str(value_unit))


@mqtt_handler("variable/+/set", "variable/+/shift")
async def handle_variable_change(
    subtopic: str,
    payload: str,
    module: Module,
    config: AppConfig,
) -> None:
    """Handle a command to change a variable value."""
    device_connection = module.device_connection
    if device_connection is None:
        return
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
    subtopic: str, payload: str, module: Module, config: AppConfig
) -> None:
    """Handle a request for the retained state of a variable."""
    if not config.retained_broker_states:
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


# ---------- Setpoints ----------


@input_handler(inputs.ModStatusVar)
def handle_setpoint_input(
    inp: inputs.ModStatusVar, module: Module
) -> Generator[MqttMessage]:
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
        yield MqttMessage(f"setpoint/{idx}/state", str(value_unit))
    if variable.update_locked(inp.value.is_locked_regulator()):
        yield MqttMessage(
            f"setpoint/{idx}/locked",
            "on" if inp.value.is_locked_regulator() else "off",
        )


@mqtt_handler(
    "setpoint/+/set", "setpoint/+/shift", "setpoint/+/offset", "setpoint/+/lock"
)
async def handle_setpoint_change(
    subtopic: str,
    payload: str,
    module: Module,
    config: AppConfig,
) -> None:
    """Handle a command to change a setpoint value."""
    device_connection = module.device_connection
    if device_connection is None:
        return
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
    subtopic: str, payload: str, module: Module, config: AppConfig
) -> None:
    """Handle a request for the retained state of a setpoint."""
    if not config.retained_broker_states:
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


# ---------- Thresholds ----------


@input_handler(inputs.ModStatusVar)
def handle_threshold_input(
    inp: inputs.ModStatusVar, module: Module
) -> Generator[MqttMessage]:
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
        yield MqttMessage(f"threshold/{register}/{idx}/state", str(value_unit))
    if threshold.update_locked(inp.value.is_locked_threshold()):
        yield MqttMessage(
            f"threshold/{register}/{idx}/locked",
            "on" if inp.value.is_locked_threshold() else "off",
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
    module: Module,
    config: AppConfig,
) -> None:
    """Handle a command to change a threshold value."""
    device_connection = module.device_connection
    if device_connection is None:
        return
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
    subtopic: str, payload: str, module: Module, config: AppConfig
) -> None:
    """Handle a request for the retained state of a threshold."""
    if not config.retained_broker_states:
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
