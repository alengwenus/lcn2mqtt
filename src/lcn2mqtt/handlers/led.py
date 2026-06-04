"""Handler for LCN LED status outputs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs, lcn_defs

from ..models import LedState, Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]


def _led_state(state: Any) -> LedState:
    name = getattr(state, "name", str(state)).lower()
    mapping = {
        "on": LedState.ON,
        "off": LedState.OFF,
        "blink": LedState.BLINK,
        "flicker": LedState.FLICKER,
    }
    return mapping.get(name, LedState.OFF)


class LedHandler:
    """Handles status updates for LCN LED outputs."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusLedsAndLogicOps, module: Module, prefix: str
    ) -> None:
        states = [_led_state(s) for s in inp.states_led]
        changed = module.update_leds(states)
        for i, did_change in enumerate(changed, start=1):
            if did_change:
                await self._publish(f"{prefix}/led/{i}/state", states[i - 1].value)

    async def handle_command(self, mc: Any, idx: int, payload: str) -> None:
        if not 1 <= idx <= 12:
            return
        status_map = {
            "on": lcn_defs.LedStatus.ON,
            "off": lcn_defs.LedStatus.OFF,
            "blink": lcn_defs.LedStatus.BLINK,
            "flicker": lcn_defs.LedStatus.FLICKER,
        }
        status = status_map.get(payload.lower())
        if status is None:
            _LOG.warning("Invalid LED payload %r", payload)
            return
        led = lcn_defs.LedPort(idx - 1)
        await mc.control_led(led, status)
