"""Handler for LCN output ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from pydantic import ValidationError
from pypck import inputs, lcn_defs

from ..models import Module, Output

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

_DEFAULT_TRANSITION_MS = 500


class OutputHandler:
    """Handles status updates and commands for LCN dimmer output ports."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusOutput, module: Module, prefix: str
    ) -> None:
        idx = inp.output_id + 1  # 0-based -> 1-based
        output = getattr(module, f"output{idx}")

        if output.update_brightness(inp.percent):
            await self._publish(f"{prefix}/output/{idx}/state", f"{inp.percent:.2f}")

    async def handle_command(
        self, mc: Any, kind: str, parts: list[str], payload: str, module: Module
    ) -> None:
        if kind != "output":
            return
        if len(parts) < 2:  # /<idx>/set or /<idx>/set_transition
            return
        try:
            idx = int(parts[0])
        except ValueError:
            return
        action = parts[1]
        if not 1 <= idx <= 4:
            return

        output: Output = getattr(module, f"output{idx}")

        if action == "set_transition":
            try:
                transition = int(payload)
                output.transition = transition
            except (ValueError, ValidationError):
                _LOG.warning("Invalid transition payload %r", payload)
                return
            return

        # action == "set"
        if payload in {"on", "true"}:
            brightness = 100.0
        elif payload in {"off", "false"}:
            brightness = 0.0
        else:
            try:
                brightness = float(payload)
            except ValueError:
                _LOG.warning("Invalid output payload %r", payload)
                return
        brightness = max(0.0, min(100.0, brightness))
        transition_ms = (
            output.transition
            if output.transition is not None
            else _DEFAULT_TRANSITION_MS
        )

        ramp = lcn_defs.time_to_ramp_value(transition_ms)
        await mc.dim_output(idx - 1, brightness, ramp)
