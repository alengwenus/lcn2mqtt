"""Handler for LCN LED status outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs
from pypck.device import DeviceConnection

from ..models import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class LedHandler:
    """Handles status updates for LCN LED outputs."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusLedsAndLogicOps, module: Module, prefix: str
    ) -> None:
        """Handle an LED status input, update the module state, and publish any changes."""
        states = [state.name.lower() for state in inp.states_led]
        changed = module.update_leds(states)
        for idx, did_change in enumerate(changed, start=1):
            if did_change:
                await self._publish(f"{prefix}/led/{idx}/state", states[idx - 1])

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
    ) -> None:
        """Handle a command to change an LED state."""
        if handler != "led":
            return
        if len(parts) < 2:  # /<idx>/set
            return
        try:
            idx = int(parts[0])
            action = parts[1]
            led = lcn_defs.LedPort(idx - 1)
        except ValueError:
            return

        if action == "state":
            return

        try:
            status = lcn_defs.LedStatus[payload.upper()]
        except KeyError:
            _LOG.warning("Invalid LED payload %r", payload)
            return

        if action == "set":
            await device_connection.control_led(led, status)
            await device_connection.request_status_leds_and_logic_ops()
