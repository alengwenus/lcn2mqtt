"""Handler for extra functionalities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models.device import Device
from .dispatcher import mqtt_handler

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@mqtt_handler("pck/set")
async def handle_pck_set(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to send a PCK message."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    await device_connection.pck(payload)


@mqtt_handler("dyn_text/#/set")
async def handle_dyn_text_set(
    subtopic: str, payload: str, module: Device, bridge: Bridge
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
