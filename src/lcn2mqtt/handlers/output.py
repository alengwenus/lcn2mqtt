"""Handler for LCN output ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from ..models import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


class OutputHandler:
    """Handles status updates and commands for LCN dimmer output ports."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusOutput, module: Module, prefix: str
    ) -> None:
        idx = inp.output_id + 1  # 0-based -> 1-based
        if module.update_output(idx, float(inp.percent)):
            await self._publish(f"{prefix}/output/{idx}", f"{inp.percent:.2f}")

    async def handle_command(self, mc: Any, idx: int, payload: str) -> None:
        if not 1 <= idx <= 4:
            return
        if payload in {"on", "true"}:
            percent = 100.0
        elif payload in {"off", "false"}:
            percent = 0.0
        else:
            try:
                percent = float(payload)
            except ValueError:
                _LOG.warning("Invalid output payload %r", payload)
                return
        percent = max(0.0, min(100.0, percent))
        ramp = lcn_defs.time_to_ramp_value(500)  # 0.5 s
        await mc.dim_output(idx - 1, percent, ramp)
