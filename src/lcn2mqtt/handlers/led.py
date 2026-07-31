"""Handler for LCN LED status outputs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device, LedState

_LOG = logging.getLogger(__name__)


if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusLedsAndLogicOps)
def handle_input(
    inp: inputs.ModStatusLedsAndLogicOps, module: Device, bridge: Bridge
) -> None:
    """Handle an LED status input, update the module state, and publish any changes."""
    states = [LedState(state.name.lower()) for state in inp.states_led]
    changed = module.update_leds(states)
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            bridge.publish(
                module.prefix, MqttMessage(f"led/{idx}/state", states[idx - 1].value)
            )


@mqtt_handler("led/+/set")
async def handle_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
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


@mqtt_handler("led/+/state")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a led."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 12:
        return

    try:
        setattr(module, f"led{idx}", LedState(payload.lower()))
    except ValueError:
        _LOG.warning("Invalid led state payload %r", payload)
        return
