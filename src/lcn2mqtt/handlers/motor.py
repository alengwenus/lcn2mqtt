"""Handler for LCN motor (blind/shutter) outputs."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from typing import Any

from pypck import inputs, lcn_defs

from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig

from ..models.device import Device, MotorState
from .dispatcher import input_handler, mqtt_handler

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


# ---------- Motors via relays ----------


@input_handler(inputs.ModStatusRelays)
def handle_motor_relays_status(
    inp: inputs.ModStatusRelays, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    states = [MotorState.OPEN] * 4
    for idx in range(4):
        motor_obj = getattr(module, f"motor{idx + 1}")
        if inp.is_opening(idx) and motor_obj.position != 100:
            states[idx] = MotorState.OPENING
        elif inp.is_closing(idx) and motor_obj.position != 0:
            states[idx] = MotorState.CLOSING
        elif motor_obj.positioning_mode in (
            lcn_defs.MotorPositioningMode.MODULE,
            lcn_defs.MotorPositioningMode.BS4,
        ):
            # open/closed is handled by positioning status inputs, so we don't need to publish anything here
            continue
        elif inp.is_assumed_closed(idx):
            states[idx] = MotorState.CLOSED
    changed = module.update_motors(states)
    for i, did_change in enumerate(changed, start=1):
        if did_change:
            yield MqttMessage(f"motor/{i}/state", states[i - 1].value)


@input_handler(inputs.ModStatusMotorPositionModule)
def handle_motor_relays_position_module_status(
    inp: inputs.ModStatusMotorPositionModule, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    motor = inp.motor + 1
    position = inp.position

    motor_obj = getattr(module, f"motor{motor}")

    if position == 100:
        yield MqttMessage(f"motor/{motor}/state", MotorState.OPEN.value)
    elif position == 0:
        yield MqttMessage(f"motor/{motor}/state", MotorState.CLOSED.value)

    did_change = motor_obj.update_position(position)
    if did_change:
        yield MqttMessage(f"motor/{motor}/position", f"{position}")


@input_handler(inputs.ModStatusMotorPositionBS4)
def handle_motor_position_module_bs4(
    inp: inputs.ModStatusMotorPositionBS4, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    motor = inp.motor + 1
    position = inp.position

    motor_obj = getattr(module, f"motor{motor}")
    did_change = motor_obj.update_position(position)

    if did_change:
        yield MqttMessage(f"motor/{motor}/position", f"{position}")


@mqtt_handler("motor/+/set", "motor/+/set_position")
async def handle_motor_relays_set(
    subtopic: str,
    payload: str,
    module: Device,
    config: AppConfig,
) -> None:
    """Handle a command to change a motor state."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    if parts[1] == "outputs":
        return
    try:
        idx = int(parts[1])
        action = parts[2]
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    motor_obj = getattr(module, f"motor{idx}")
    positioning_mode = motor_obj.positioning_mode

    if action == "set":
        modifier_map = {
            "open": lcn_defs.MotorStateModifier.UP,
            "up": lcn_defs.MotorStateModifier.UP,
            "close": lcn_defs.MotorStateModifier.DOWN,
            "down": lcn_defs.MotorStateModifier.DOWN,
            "stop": lcn_defs.MotorStateModifier.STOP,
        }
        modifier = modifier_map.get(payload)
        if modifier is None:
            return
        await device_connection.control_motor_relays(
            idx - 1, modifier, positioning_mode
        )
    elif action == "set_position":
        if positioning_mode not in (
            lcn_defs.MotorPositioningMode.MODULE,
            lcn_defs.MotorPositioningMode.BS4,
        ):
            _LOG.warning(
                "Motor %d is not in a positioning mode, cannot set position", idx
            )
            return
        try:
            position = int(payload)
        except ValueError as exc:
            raise ValueError(f"Invalid position payload: {payload}") from exc
        await device_connection.control_motor_relays_position(
            idx - 1, position, positioning_mode
        )


# ---------- Motors via outputs ----------


@input_handler(inputs.ModStatusOutput)
def handle_motor_outputs_status(
    inp: inputs.ModStatusOutput, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor output status input, update the module state, and publish any changes."""
    motor_obj = module.motor_outputs

    if motor_obj.positioning_mode == lcn_defs.MotorPositioningMode.MODULE:
        # final state is resolved directly from position/set events, not from
        # the (possibly dimmed/delayed) output percentage
        return

    if inp.get_percent() > 0:  # motor is on
        if inp.get_output_id() == lcn_defs.OutputPort.OUTPUTUP.value:
            state = MotorState.OPENING
        elif inp.get_output_id() == lcn_defs.OutputPort.OUTPUTDOWN.value:
            state = MotorState.CLOSING
        else:
            return
    elif (
        inp.get_output_id() == lcn_defs.OutputPort.OUTPUTDOWN.value
        and motor_obj.state == MotorState.CLOSING
    ):
        state = MotorState.CLOSED
    elif (
        inp.get_output_id() == lcn_defs.OutputPort.OUTPUTUP.value
        and motor_obj.state == MotorState.OPENING
    ):
        state = MotorState.OPEN
    else:
        return

    changed = motor_obj.update_state(state)
    if changed:
        yield MqttMessage("motor/outputs/state", state.value)


@input_handler(inputs.ModStatusMotorPositionModule)
def handle_motor_outputs_position_module_status(
    inp: inputs.ModStatusMotorPositionModule, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    motor_obj = module.motor_outputs
    if motor_obj.positioning_mode != lcn_defs.MotorPositioningMode.MODULE:
        return

    motor = inp.motor + 1
    position = inp.position

    if motor != 4:
        return  # only handle motor 4 for outputs

    old_position = motor_obj.position

    did_change = motor_obj.update_position(position)
    if did_change:
        yield MqttMessage("motor/outputs/position", f"{position}")

    target = motor_obj.target_position
    reached_target = target is not None and position == target
    reached_endstop = position in (0, 100) and target is None

    if reached_target or reached_endstop:
        state = MotorState.OPEN if position > 0 else MotorState.CLOSED
        changed = motor_obj.update_state(state)
        if changed:
            yield MqttMessage("motor/outputs/state", state.value)
        return

    if old_position is not None and position > old_position:
        state = MotorState.OPENING
    elif old_position is not None and position < old_position:
        state = MotorState.CLOSING
    else:
        return

    changed = motor_obj.update_state(state)
    if changed:
        yield MqttMessage("motor/outputs/state", state.value)


@mqtt_handler("motor/outputs/set", "motor/outputs/set_position")
async def handle_motor_outputs_set(
    subtopic: str,
    payload: str,
    module: Device,
    config: AppConfig,
) -> AsyncGenerator[MqttMessage]:
    """Handle a command to change a motor state."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        action = parts[2]
    except ValueError:
        return

    motor_obj = module.motor_outputs

    if action == "set":
        if payload == "stop":
            await device_connection.control_motor_outputs(
                lcn_defs.MotorStateModifier.STOP, motor_obj.reverse_time
            )
            motor_obj.target_position = motor_obj.position
            if motor_obj.position is not None:
                state = (
                    MotorState.OPEN if motor_obj.position > 0 else MotorState.CLOSED
                )
                if motor_obj.update_state(state):
                    yield MqttMessage("motor/outputs/state", state.value)
            return

        modifier_map = {
            "open": lcn_defs.MotorStateModifier.UP,
            "up": lcn_defs.MotorStateModifier.UP,
            "close": lcn_defs.MotorStateModifier.DOWN,
            "down": lcn_defs.MotorStateModifier.DOWN,
        }
        modifier = modifier_map.get(payload)
        if modifier is None:
            return
        motor_obj.target_position = None
        await device_connection.control_motor_outputs(
            modifier, motor_obj.reverse_time
        )
    elif action == "set_position":
        positioning_mode = motor_obj.positioning_mode
        if positioning_mode != lcn_defs.MotorPositioningMode.MODULE:
            _LOG.warning(
                "Outputs motor is not in a positioning mode, cannot set position"
            )
            return
        try:
            position = int(payload)
        except ValueError as exc:
            raise ValueError(f"Invalid position payload: {payload}") from exc
        motor_obj.target_position = position
        await device_connection.control_motor_outputs_position(
            position, positioning_mode
        )


# ---------- Retained state ----------


@mqtt_handler("motor/+/state", "motor/+/position")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, config: AppConfig
) -> None:
    """Handle a request for the retained state of a motor."""
    if not config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        if not 1 <= idx <= 4:
            return
        motor = f"motor{idx}"
    except ValueError:
        if parts[1] != "outputs":
            return
        motor = "motor_outputs"

    action = parts[2]

    motor_obj = getattr(module, motor)
    if action == "state":
        try:
            motor_obj.state = MotorState(payload.lower())
        except ValueError:
            _LOG.warning("Invalid motor state payload %r", payload)
    elif action == "position":
        try:
            motor_obj.position = float(payload)
        except ValueError:
            _LOG.warning("Invalid motor position payload %r", payload)
        return
