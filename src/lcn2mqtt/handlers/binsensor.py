"""Handler for LCN binary sensors."""

import logging

from pypck import inputs

from lcn2mqtt.handlers.dispatcher import input_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.module import Module

_LOG = logging.getLogger(__name__)


@input_handler(inputs.ModStatusBinSensors)
async def handle_binsensor_input(
    inp: inputs.ModStatusBinSensors, module: Module
) -> list[MqttMessage]:
    """Handle binary sensors status input, update the module state, and publish any changes."""
    changed: list[bool] = module.update_binaries(inp.states)
    messages: list[MqttMessage] = []
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            messages.append(
                MqttMessage(
                    f"binsensor/{idx}/state", "on" if inp.states[idx - 1] else "off"
                )
            )
    return messages
