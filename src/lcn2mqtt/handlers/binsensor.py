"""Handler for LCN binary sensors."""

import logging
from collections.abc import Generator

from pypck import inputs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import AppConfig

from ..models.module import Module

_LOG = logging.getLogger(__name__)


@input_handler(inputs.ModStatusBinSensors)
def handle_binsensor_input(
    inp: inputs.ModStatusBinSensors, module: Module
) -> Generator[MqttMessage]:
    """Handle binary sensors status input, update the module state, and publish any changes."""
    changed: list[bool] = module.update_binaries(inp.states)
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            yield MqttMessage(
                f"binsensor/{idx}/state", "on" if inp.states[idx - 1] else "off"
            )


@mqtt_handler("binsensor/+/state")
async def handle_retained_state(
    subtopic: str, payload: str, module: Module, config: AppConfig
) -> None:
    """Handle a request for the retained state of a binary sensor."""
    if not config.retained_broker_states:
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
