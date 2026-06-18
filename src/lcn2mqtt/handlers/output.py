"""Handler for LCN output ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from pydantic import ValidationError
from pypck import inputs, lcn_defs
from pypck.device import DeviceConnection

from ..models.module import Module, Output, OutputState

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

_DEFAULT_TRANSITION_MS = 500


class OutputHandler:
    """Handles status updates and commands for LCN dimmer output ports."""

    def __init__(self, publish: Publish) -> None:
        """Initialize the handler with a publish function."""
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusOutput, module: Module, prefix: str
    ) -> None:
        """Handle an output status input, update the module state, and publish any changes."""
        idx = inp.output_id + 1  # 0-based -> 1-based
        output = getattr(module, f"output{idx}")

        state_changed = output.update_state(
            OutputState.ON if inp.percent > 0 else OutputState.OFF
        )
        output.update_brightness(inp.percent)

        if state_changed:
            await self._publish(
                f"{prefix}/output/{idx}/state",
                output.state.value if output.state else None,
            )
        await self._publish(f"{prefix}/output/{idx}/brightness", f"{inp.percent:.2f}")

    async def handle_command(
        self,
        device_connection: DeviceConnection,
        handler: str,
        parts: list[str],
        payload: str,
        module: Module,
    ) -> None:
        """Handle a command to change an output state or brightness."""
        if handler != "output":
            return
        # /<idx>/set
        # /<idx>/set_brightness
        # /<idx>/set_transition
        if len(parts) < 2:
            return
        try:
            idx = int(parts[0])
        except ValueError:
            return
        action = parts[1]
        if not 1 <= idx <= 4:
            return

        output: Output = getattr(module, f"output{idx}")

        if action == "set_brightness":
            try:
                brightness = float(payload)
                output.brightness = brightness
            except (ValueError, ValidationError):
                _LOG.warning("Invalid brightness payload %r", payload)
                return
        elif action == "set_transition":
            try:
                transition = int(payload)
                output.transition = transition
            except (ValueError, ValidationError):
                _LOG.warning("Invalid transition payload %r", payload)
                return
            return
        elif action == "set":
            transition_ms = (
                output.transition
                if output.transition is not None
                else _DEFAULT_TRANSITION_MS
            )
            ramp = lcn_defs.time_to_ramp_value(transition_ms)

            if payload == "on":
                if output.state == OutputState.OFF:
                    await device_connection.toggle_output(idx - 1, ramp, to_memory=True)
                    return
                brightness = (
                    output.brightness if output.brightness is not None else 100.0
                )
            elif payload == "off":
                if output.state == OutputState.ON:
                    await device_connection.toggle_output(idx - 1, ramp, to_memory=True)
                    return
                brightness = 0.0
            else:  # payload is a brightness value
                try:
                    brightness = float(payload)
                except ValueError:
                    _LOG.warning("Invalid output payload %r", payload)
                    return
            brightness = max(0.0, min(100.0, brightness))

            await device_connection.dim_output(idx - 1, brightness, ramp)
