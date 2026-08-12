"""Handler for LCN relay outputs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pypck import inputs, lcn_defs

from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device, RelayState
from .dispatcher import input_handler, mqtt_handler

_LOG = logging.getLogger(__name__)


if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusRelays)
def handle_relay_status(
    inp: inputs.ModStatusRelays,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a relay status input, update the module state, and publish any changes."""
    states = [RelayState.ON if s else RelayState.OFF for s in inp.states]
    changed = module.update_relays(states)
    for i, did_change in enumerate(changed, start=1):
        if did_change:
            bridge.publish(
                module.prefix, MqttMessage(f"relay/{i}/state", states[i - 1].value)
            )


@mqtt_handler("relay/+/set")
async def handle_set(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to change a relay state."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 8:
        return

    modifier_map = {
        "on": lcn_defs.RelayStateModifier.ON,
        "off": lcn_defs.RelayStateModifier.OFF,
        "toggle": lcn_defs.RelayStateModifier.TOGGLE,
    }
    modifier = modifier_map.get(payload)
    if modifier is None:
        _LOG.warning("Invalid relay payload %r", payload)
        return
    states = [lcn_defs.RelayStateModifier.NOCHANGE] * 8
    states[idx - 1] = modifier
    await device_connection.control_relays(states)


@mqtt_handler("relay/+/state")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a relay."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 8:
        return

    try:
        setattr(module, f"relay{idx}", RelayState(payload.lower()))
    except ValueError:
        _LOG.warning("Invalid relay state payload %r", payload)
        return


@mqtt_handler("relay/+/get", "relay/get")
async def handle_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current state of a relay."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        if parts[1] == "get":
            idxs = list(range(1, 9))
        else:
            idx = int(parts[1])
            if not 1 <= idx <= 8:
                return
            idxs = [idx]
    except ValueError:
        return

    result_input = await device_connection.request_status_relays()
    if result_input is None:
        return

    for i in idxs:
        state = RelayState.ON if result_input.states[i - 1] else RelayState.OFF
        bridge.publish(
            module.prefix,
            MqttMessage(f"relay/{i}/state", state.value),
        )
