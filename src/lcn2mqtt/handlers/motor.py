"""Handler for LCN motor (blind/shutter) outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Generator
from typing import Any

from pypck import inputs, lcn_defs

from lcn2mqtt.helpers import DeferredMqttMessage, MqttMessage
from lcn2mqtt.models.config import AppConfig

from ..models.device import Device, MotorState
from .dispatcher import input_handler, mqtt_handler

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

# Default inactivity timeout for positioning mode. Position updates arrive every ~2 s;
# 5 s without an update means the motor has stopped.
_STOP_TIMEOUT_POSITIONING = 5.0  # seconds


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
    """Handle a motor position status input, update the module state, and publish any changes."""
    # In MODULE positioning mode the output-status is unreliable and arrives with a large delay;
    # state is tracked accurately via ModStatusMotorPositionModule updates instead.
    if module.motor_outputs.positioning_mode == lcn_defs.MotorPositioningMode.MODULE:
        return

    state = MotorState.UNKNOWN
    # No positioning mode: derive state from the output port and direction.
    if inp.get_percent() > 0:  # motor is on
        if inp.get_output_id() == lcn_defs.OutputPort.OUTPUTUP.value:
            state = MotorState.OPENING
        elif inp.get_output_id() == lcn_defs.OutputPort.OUTPUTDOWN.value:
            state = MotorState.CLOSING

    # Motor is off: Cover is assumed to be closed if we were in closing state before
    elif (
        inp.get_output_id() == lcn_defs.OutputPort.OUTPUTDOWN.value
        and module.motor_outputs.state == MotorState.CLOSING
    ):
        state = MotorState.CLOSED
    elif (
        inp.get_output_id() == lcn_defs.OutputPort.OUTPUTUP.value
        and module.motor_outputs.state == MotorState.OPENING
    ):
        state = MotorState.OPEN

    changed = module.motor_outputs.update_state(state)
    if changed:
        yield MqttMessage("motor/outputs/state", state.value)


@input_handler(inputs.ModStatusMotorPositionModule)
def handle_motor_outputs_position_module_status(
    inp: inputs.ModStatusMotorPositionModule, module: Device
) -> Generator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    if module.motor_outputs.positioning_mode != lcn_defs.MotorPositioningMode.MODULE:
        return

    motor = inp.motor + 1
    position = inp.position

    if motor != 4:
        return  # only handle motor 4 for outputs

    old_position = module.motor_outputs.position

    did_change = module.motor_outputs.update_position(position)
    if did_change:
        yield MqttMessage("motor/outputs/position", f"{position}")

    if position == 100:
        new_state = MotorState.OPEN
    elif position == 0:
        new_state = MotorState.CLOSED
    elif old_position is not None and position > old_position:
        new_state = MotorState.OPENING
    elif old_position is not None and position < old_position:
        new_state = MotorState.CLOSING
    else:
        return  # direction not yet determinable (first update)

    if module.motor_outputs.update_state(new_state):
        yield MqttMessage("motor/outputs/state", new_state.value)

    # Schedule or cancel the inactivity stop timer.
    # In positioning mode any intermediate stop means "not fully closed" = OPEN.
    if new_state in (MotorState.OPENING, MotorState.CLOSING):
        yield DeferredMqttMessage(
            topic="motor/outputs/state",
            payload=MotorState.OPEN.value,
            delay=(
                module.motor_outputs.stop_timeout
                if module.motor_outputs.stop_timeout is not None
                else _STOP_TIMEOUT_POSITIONING
            ),
        )
    else:
        # Motor reached end position (OPEN or CLOSED) – cancel any pending stop timer.
        yield DeferredMqttMessage(topic="motor/outputs/state", payload=new_state.value)


@mqtt_handler("motor/outputs/set", "motor/outputs/set_position")
async def handle_motor_outputs_set(
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
    try:
        action = parts[2]
    except ValueError:
        return

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
        await device_connection.control_motor_outputs(
            modifier, module.motor_outputs.reverse_time
        )
    elif action == "set_position":
        positioning_mode = module.motor_outputs.positioning_mode
        if positioning_mode != lcn_defs.MotorPositioningMode.MODULE:
            _LOG.warning(
                "Outputs motor is not in a positioning mode, cannot set position"
            )
            return
        try:
            position = int(payload)
        except ValueError as exc:
            raise ValueError(f"Invalid position payload: {payload}") from exc
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
