"""Handler for LCN motor (blind/shutter) outputs."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from lcn2mqtt.helpers import MqttMessage

from ..models.module import Module, MotorState
from .dispatcher import input_handler, mqtt_handler

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


@input_handler(inputs.ModStatusRelays)
async def handle_relays_status(
    inp: inputs.ModStatusRelays, module: Module
) -> AsyncGenerator[MqttMessage]:
    """Handle a motor position status input, update the module state, and publish any changes."""
    states = [MotorState.OPEN] * 4
    for idx in range(4):
        if inp.is_opening(idx):
            states[idx] = MotorState.OPENING
        elif inp.is_closing(idx):
            states[idx] = MotorState.CLOSING
        elif inp.is_assumed_closed(idx):
            states[idx] = MotorState.CLOSED
    changed = module.update_motors(states)
    for i, did_change in enumerate(changed, start=1):
        if did_change:
            yield MqttMessage(f"motor_relays/{i}/state", states[i - 1].value)


@mqtt_handler("motor_relays/+/set")
async def handle_set(
    subtopic: str,
    payload: str,
    module: Module,
) -> None:
    """Handle a command to change a motor state."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        action = parts[2]
    except ValueError:
        return
    if not 1 <= idx <= 4:
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
        await device_connection.control_motor_relays(idx - 1, modifier)
