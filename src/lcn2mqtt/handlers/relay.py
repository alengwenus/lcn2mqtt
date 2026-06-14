"""Handler for LCN relay outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs
from pypck.device import DeviceConnection

from ..module import Module, RelayState

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class RelayHandler:
    """Handles status updates and commands for LCN relay outputs."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusRelays, module: Module, prefix: str
    ) -> None:
        """Handle a relay status input, update the module state, and publish any changes."""
        states = [RelayState.ON if s else RelayState.OFF for s in inp.states]
        changed = module.update_relays(states)
        for i, did_change in enumerate(changed, start=1):
            if did_change:
                await self._publish(f"{prefix}/relay/{i}/state", states[i - 1].value)

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
    ) -> None:
        """Handle a command to change a relay state."""
        if handler != "relay":
            return
        if len(parts) < 2:  # /<idx>/set
            return
        try:
            idx = int(parts[0])
            action = parts[1]
        except ValueError:
            return
        if not 1 <= idx <= 8:
            return
        if action != "set":
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
