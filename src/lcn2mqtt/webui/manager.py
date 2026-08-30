"""Bridge lifecycle manager for the NiceGUI WebUI."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..bridge import Bridge
from ..models.config import AppConfig, load_config

_LOG = logging.getLogger(__name__)


class BridgeManager:
    """Manages the bridge asyncio task within NiceGUI's event loop."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the manager with the given config."""
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self.restart_needed: bool = False

    @property
    def is_running(self) -> bool:
        """Return True if the bridge task is currently active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the bridge as a background asyncio task."""
        if self.is_running:
            return
        bridge = Bridge(self.config)
        self._task = asyncio.create_task(bridge.run(), name="bridge")
        _LOG.info("Bridge started")

    async def stop(self) -> None:
        """Cancel and await the bridge task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        _LOG.info("Bridge stopped")

    async def restart(self) -> None:
        """Stop, reload config from YAML, and restart the bridge."""
        await self.stop()
        self.config = load_config()
        await self.start()
        _LOG.info("Bridge restarted")
