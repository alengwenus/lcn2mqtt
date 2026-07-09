"""Handler for extra functionalities."""

import logging

from lcn2mqtt.models.config import AppConfig

from ..models.device import Device
from .dispatcher import mqtt_handler

_LOG = logging.getLogger(__name__)


@mqtt_handler("pck/set")
async def handle_pck_set(
    subtopic: str, payload: str, module: Device, config: AppConfig
) -> None:
    """Handle a command to send a PCK message."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    await device_connection.pck(payload)


@mqtt_handler("dyn_text/#/set")
async def handle_dyn_text_set(
    subtopic: str, payload: str, module: Device, config: AppConfig
) -> None:
    """Handle a command to send a dynamic text message."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return
    try:
        await device_connection.dyn_text(idx - 1, payload)
    except ValueError:
        _LOG.warning("Invalid dyn_text payload %r", payload)
