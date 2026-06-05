"""Handler for LCN motor (blind/shutter) outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from ..models import Module, MotorState

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class MotorRelayHandler:
    """Handles status updates and commands for LCN motor outputs."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusRelays, module: Module, prefix: str
    ) -> None:
        """Handle a motor position status input, update the module state, and publish any changes."""
        states = [MotorState.OPEN] * 4
        for idx in range(4):
            if inp.is_opening(idx):
                states[idx] = MotorState.OPENING
            elif inp.is_closing(idx):
                states[idx] = MotorState.CLOSING
            elif inp.is_assumed_closed(idx):
                states[idx] = MotorState.CLOSED
        changed = module.update_motors(states)
        for i, did_change in enumerate(changed, start=1):
            if did_change:
                await self._publish(
                    f"{prefix}/motor_relays/{i}/state", states[i - 1].value
                )

    async def handle_command(
        self, mc: Any, handler: str, parts: list[str], payload: str
    ) -> None:
        """Handle a command to change a motor state."""
        if handler != "motor_relays":
            return
        if len(parts) < 1:
            return
        try:
            idx = int(parts[0])
            action = parts[1]
        except ValueError:
            return
        if not 1 <= idx <= 4:
            return

        if action == "set":
            modifier_map = {
                "open": lcn_defs.MotorStateModifier.UP,
                "up": lcn_defs.MotorStateModifier.UP,
                "close": lcn_defs.MotorStateModifier.DOWN,
                "down": lcn_defs.MotorStateModifier.DOWN,
                "stop": lcn_defs.MotorStateModifier.STOP,
            }
            modifier = modifier_map.get(payload)
            if modifier is None:
                return
            await mc.control_motor_relays(idx - 1, modifier)
