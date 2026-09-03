"""Bridge lifecycle manager for the NiceGUI WebUI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from itertools import chain

from pypck import lcn_defs
from pypck.device import DeviceConnection
from pypck.lcn_addr import LcnAddr

from ..bridge import Bridge
from ..models.config import AppConfig, DeviceConfig, load_config

_LOG = logging.getLogger(__name__)


class BridgeManager:
    """Manages the bridge asyncio task within NiceGUI's event loop."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the manager with the given config."""
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._bridge: Bridge | None = None
        self.restart_needed: bool = False

    @property
    def is_running(self) -> bool:
        """Return True if the bridge task is currently active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the bridge as a background asyncio task."""
        if self.is_running:
            return
        self._bridge = Bridge(self.config)
        self._task = asyncio.create_task(self._bridge.run(), name="bridge")
        _LOG.info("Bridge started")

    async def stop(self) -> None:
        """Cancel and await the bridge task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._bridge = None
        _LOG.info("Bridge stopped")

    async def restart(self) -> None:
        """Stop, reload config from YAML, and restart the bridge."""
        await self.stop()
        self.config = load_config()
        await self.start()
        _LOG.info("Bridge restarted")

    @property
    def devices(self) -> dict[LcnAddr, DeviceConfig]:
        """Return the devices known to the running bridge (empty if stopped)."""
        if self._bridge is None:
            return {}
        return self._bridge.devices

    async def scan_modules(self) -> list[str]:
        """Scan the LCN bus; return address strings of discovered modules."""
        if self._bridge is None or not self.is_running:
            raise RuntimeError("Bridge is not running")
        pchk = getattr(self._bridge, "_pchk", None)
        if pchk is None:
            raise RuntimeError("Bridge is not yet connected")
        await pchk.scan_modules()
        return [
            addr.to_string() for addr in pchk.device_connections if not addr.is_group
        ]

    async def poll_bus_status(self) -> None:
        """Request fresh status from all known non-group modules on the bus."""
        if self._bridge is None or not self.is_running:
            raise RuntimeError("Bridge is not running")
        for lcn_addr, device in self._bridge.devices.items():
            if lcn_addr.is_group:
                continue
            try:
                conn = await self._bridge.ensure_device_complete(lcn_addr)
                device_connection = conn.device_connection
            except Exception:  # noqa: BLE001
                _LOG.warning(
                    "Cannot poll status for %s: no device connection",
                    lcn_addr.to_string(),
                )
                continue
            await self._poll_module_status(device, device_connection)
            # small delay to avoid flooding the bus
            await asyncio.sleep(0.1)

    @staticmethod
    async def _poll_module_status(
        device: DeviceConfig, device_connection: DeviceConnection
    ) -> None:
        """Issue status requests for a single module."""
        serial = device_connection.serials.software_serial

        for port in lcn_defs.OutputPort:
            await device_connection.request_status_output(port, max_age=0)
        await device_connection.request_status_relays(max_age=0)
        await device_connection.request_status_binary_sensors(max_age=0)
        await device_connection.request_status_leds_and_logic_ops(max_age=0)

        variables = list(lcn_defs.Var.variables())
        variables += lcn_defs.Var.set_points()
        if serial >= 0x170206:
            thresholds = list(chain.from_iterable(lcn_defs.Var.thresholds_new()))
        else:
            thresholds = list(chain.from_iterable(lcn_defs.Var.thresholds_old()))
        variables += thresholds
        for var in variables:
            await device_connection.request_status_variable(var, max_age=0)

        for motor in (
            lcn_defs.MotorPort.MOTOR1,
            lcn_defs.MotorPort.MOTOR2,
            lcn_defs.MotorPort.MOTOR3,
            lcn_defs.MotorPort.MOTOR4,
        ):
            await device_connection.request_status_motor_position(
                motor,
                lcn_defs.MotorPositioningMode.BS4,
                max_age=0,
            )
