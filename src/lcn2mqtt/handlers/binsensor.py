"""Handler for LCN binary sensors."""

import logging
from typing import TYPE_CHECKING

from pypck import inputs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusBinSensors)
def handle_binsensor_input(
    inp: inputs.ModStatusBinSensors, module: Device, bridge: Bridge
) -> None:
    """Handle binary sensors status input, update the module state, and publish any changes."""
    changed: list[bool] = module.update_binaries(inp.states)
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            bridge.publish(
                module.prefix,
                MqttMessage(
                    f"binsensor/{idx}/state", "on" if inp.states[idx - 1] else "off"
                ),
            )


@mqtt_handler("binsensor/+/state")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a binary sensor."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 8:
        return

    if payload.lower() not in ("on", "off"):
        _LOG.warning("Invalid binary sensor state payload %r", payload)
        return

    setattr(module, f"binsensor{idx}", payload.lower() == "on")


@mqtt_handler("binsensor/+/get", "binsensor/get")
async def handle_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current state of a binary sensor."""
    device_connection = module.device_connection
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

    result_input = await device_connection.request_status_binary_sensors()
    if result_input is None:
        return

    for i in idxs:
        state = "on" if result_input.states[i - 1] else "off"
        bridge.publish(
            module.prefix,
            MqttMessage(f"binsensor/{i}/state", state),
        )
