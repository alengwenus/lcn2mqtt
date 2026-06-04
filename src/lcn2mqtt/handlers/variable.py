"""Handler for LCN variables."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pypck import inputs

from ..models import Module

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

_VAR_INDEX_MAP = {
    "VAR1ORTVAR": 1,
    "VAR2ORR1VAR": 2,
    "VAR3ORR2VAR": 3,
    "VAR4": 4,
    "VAR5": 5,
    "VAR6": 6,
    "VAR7": 7,
    "VAR8": 8,
    "VAR9": 9,
    "VAR10": 10,
    "VAR11": 11,
    "VAR12": 12,
}


def _var_index(var: Any) -> int | None:
    name = getattr(var, "name", "")
    if not isinstance(name, str):
        return None
    if name in _VAR_INDEX_MAP:
        return _VAR_INDEX_MAP[name]
    upper = name.upper()
    if upper.startswith("VAR"):
        try:
            return int(upper[3:])
        except ValueError:
            return None
    return None


class VariableHandler:
    """Handles status updates for LCN variables."""

    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def handle_input(
        self, inp: inputs.ModStatusVar, module: Module, prefix: str
    ) -> None:
        idx = _var_index(inp.orig_var)
        if idx is None:
            return
        value = int(inp.value.to_native())
        if module.update_variable(idx, value):
            await self._publish(f"{prefix}/var/{idx}/state", value)
