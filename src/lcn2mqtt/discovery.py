"""Home Assistant MQTT Discovery for LCN modules."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiomqtt
from pypck.connection import DeviceConnection, PchkConnectionManager
from pypck.lcn_addr import LcnAddr

from . import __version__
from .config import AppConfig

_LOG = logging.getLogger(__name__)


class DiscoveryPublisher:
    """Publishes HA MQTT device-discovery messages for LCN modules."""

    def __init__(self, config: AppConfig, mqtt: aiomqtt.Client) -> None:
        self._config = config
        self._mqtt = mqtt

    # ---------- helpers ----------

    def _bridge_identifier(self) -> str:
        return f"lcn2mqtt_{self._config.mqtt.base_topic}"

    def _addr_str(self, addr: LcnAddr) -> str:
        kind = "g" if addr.is_group else "m"
        return f"{kind}{addr.seg_id:03d}{addr.addr_id:03d}"

    def _addr_prefix(self, addr: LcnAddr) -> str:
        return f"{self._config.mqtt.base_topic}/{self._addr_str(addr)}"

    def _availability(self) -> list[dict[str, str]]:
        bridge_status = f"{self._config.mqtt.base_topic}/bridge/status"
        return [
            {
                "topic": bridge_status,
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ]

    async def _publish_device(self, object_id: str, payload: dict[str, Any]) -> None:
        """Publish a device discovery payload (component=device)."""
        prefix = self._config.discovery.prefix
        topic = f"{prefix}/device/{object_id}/config"
        payload["o"] = {
            "name": self._config.mqtt.base_topic,
            "sw": __version__,
            "url": "https://github.com/alengwenus/lcn2mqtt",
        }
        await self._mqtt.publish(
            topic,
            payload=json.dumps(payload),
            qos=self._config.mqtt.qos,
            retain=True,
        )
        _LOG.debug("Discovery published: %s", topic)

    # ---------- component builders ----------

    def _output_components(self, addr_str: str, prefix: str) -> dict[str, Any]:
        cmps: dict[str, Any] = {}
        for i in range(1, 5):
            uid = f"lcn2mqtt_{addr_str}_output{i}"
            cmps[uid] = {
                "p": "light",
                "unique_id": uid,
                "name": f"Output {i}",
                "state_topic": f"{prefix}/output/{i}/state",
                "command_topic": f"{prefix}/output/{i}/set",
                "brightness_state_topic": (f"{prefix}/output/{i}/brightness"),
                "brightness_command_topic": (f"{prefix}/output/{i}/set_brightness"),
                "brightness_scale": 100,
                "payload_on": "on",
                "payload_off": "off",
            }
        return cmps

    def _relay_components(self, addr_str: str, prefix: str) -> dict[str, Any]:
        cmps: dict[str, Any] = {}
        for i in range(1, 9):
            uid = f"lcn2mqtt_{addr_str}_relay{i}"
            cmps[uid] = {
                "p": "switch",
                "unique_id": uid,
                "name": f"Relay {i}",
                "state_topic": f"{prefix}/relay/{i}/state",
                "command_topic": f"{prefix}/relay/{i}/set",
                "payload_on": "on",
                "payload_off": "off",
                "state_on": "on",
                "state_off": "off",
            }
        return cmps

    def _motor_components(self, addr_str: str, prefix: str) -> dict[str, Any]:
        cmps: dict[str, Any] = {}
        for i in range(1, 5):
            uid = f"lcn2mqtt_{addr_str}_motor{i}"
            cmps[uid] = {
                "p": "cover",
                "unique_id": uid,
                "name": f"Motor {i}",
                "state_topic": f"{prefix}/motor/{i}/state",
                "value_template": "{{ value_json.state }}",
                "command_topic": f"{prefix}/motor/{i}/set",
                "payload_open": "open",
                "payload_close": "close",
                "payload_stop": "stop",
                "state_open": "open",
                "state_closed": "closed",
                "state_opening": "opening",
                "state_closing": "closing",
            }
        return cmps

    # ---------- public API ----------

    async def publish_module(self, addr: LcnAddr, module_name: str | None) -> None:
        """Publish a device-discovery entry for one LCN module."""
        addr_str = self._addr_str(addr)
        prefix = self._addr_prefix(addr)
        display_name = module_name.strip() if module_name else f"LCN {addr_str.upper()}"
        cmps: dict[str, Any] = {}
        cmps.update(self._output_components(addr_str, prefix))
        cmps.update(self._relay_components(addr_str, prefix))
        cmps.update(self._motor_components(addr_str, prefix))
        await self._publish_device(
            f"lcn2mqtt_{addr_str}",
            {
                "dev": {
                    "identifiers": [f"lcn2mqtt_{addr_str}"],
                    "name": display_name,
                    "manufacturer": "Issendorff",
                    "model": "LCN Module",
                    "via_device": self._bridge_identifier(),
                },
                "availability": self._availability(),
                "cmps": cmps,
            },
        )

    async def publish_bridge(self) -> None:
        """Publish a device-discovery entry for the bridge itself."""
        base = self._config.mqtt.base_topic
        bridge_id = self._bridge_identifier()
        status_uid = f"{bridge_id}_status"
        await self._publish_device(
            bridge_id,
            {
                "dev": {
                    "identifiers": [bridge_id],
                    "name": base,
                    "manufacturer": "lcn2mqtt",
                    "model": "LCN-PCHK Bridge",
                },
                "availability": self._availability(),
                "cmps": {
                    status_uid: {
                        "p": "sensor",
                        "unique_id": status_uid,
                        "name": "Status",
                        "state_topic": f"{base}/bridge/status",
                    }
                },
            },
        )
        _LOG.info("Discovery: bridge published")

    async def publish_modules(self, pchk: PchkConnectionManager) -> None:
        """Scan LCN modules (optional) and publish module discovery entries."""
        cfg = self._config.discovery

        if cfg.scan_modules:
            _LOG.info("Discovery: scanning LCN bus for modules …")
            await pchk.scan_modules()

        connections: dict[LcnAddr, DeviceConnection] = pchk.device_connections
        if not connections:
            _LOG.warning("Discovery: no modules found on LCN bus")
            return

        _LOG.info(
            "Discovery: publishing config for %d module(s)",
            len(connections),
        )
        for addr, conn in list(connections.items()):
            if addr.is_group:
                continue
            module_name: str | None = None
            try:
                module_name = await conn.request_name()
            except Exception:  # noqa: BLE001
                _LOG.debug("Discovery: could not fetch name for %s", addr)

            _LOG.info(
                "Discovery: module %03d.%03d → %s",
                addr.seg_id,
                addr.addr_id,
                f'"{module_name.strip()}"' if module_name else "unnamed",
            )
            await self.publish_module(addr, module_name)

        _LOG.info("Discovery: done")
