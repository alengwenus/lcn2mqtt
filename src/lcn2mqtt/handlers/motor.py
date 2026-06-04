"""Handler for LCN motor (blind/shutter) outputs."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from ..models import Module, Motor

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class MotorHandler:
    """Handles status updates and commands for LCN motor outputs."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusMotorPositionBS4, module: Module, prefix: str
    ) -> None:
        idx = inp.motor + 1  # 0-based -> 1-based
        motor = getattr(module, f"motor{idx}") or Motor()
        motor = motor.model_copy(update={"position": float(inp.position)})
        module_motors = [getattr(module, f"motor{n}") for n in range(1, 5)]
        module_motors[idx - 1] = motor
        changed = module.update_motors(module_motors)
        if changed[idx - 1]:
            await self._publish(
                f"{prefix}/motor/{idx}",
                json.dumps(motor.model_dump(mode="json")),
            )

    async def handle_command(self, mc: Any, idx: int, payload: str) -> None:
        if not 1 <= idx <= 4:
            return
        modifier_map = {
            "open": lcn_defs.MotorStateModifier.UP,
            "up": lcn_defs.MotorStateModifier.UP,
            "close": lcn_defs.MotorStateModifier.DOWN,
            "down": lcn_defs.MotorStateModifier.DOWN,
            "stop": lcn_defs.MotorStateModifier.STOP,
        }
        modifier = modifier_map.get(payload)
        if modifier is None:
            _LOG.warning("Invalid motor payload %r", payload)
            return
        await mc.control_motor_relays(idx - 1, modifier)
