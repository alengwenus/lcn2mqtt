"""Handler for LCN LED status outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.module import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


@input_handler(inputs.ModStatusLedsAndLogicOps)
async def handle_input(
    inp: inputs.ModStatusLedsAndLogicOps, module: Module
) -> list[MqttMessage]:
    """Handle an LED status input, update the module state, and publish any changes."""
    states = [state.name.lower() for state in inp.states_led]
    changed = module.update_leds(states)
    messages: list[MqttMessage] = []
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            messages.append(MqttMessage(f"led/{idx}/state", states[idx - 1]))
    return messages


@mqtt_handler("led/+/set")
async def handle_command(
    subtopic: str,
    payload: str,
    module: Module,
) -> None:
    """Handle a command to change an LED state."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        led = lcn_defs.LedPort(idx - 1)
    except ValueError:
        return

    try:
        status = lcn_defs.LedStatus[payload.upper()]
    except KeyError:
        _LOG.warning("Invalid LED payload %r", payload)
        return

    await device_connection.control_led(led, status)
    await device_connection.request_status_leds_and_logic_ops()
