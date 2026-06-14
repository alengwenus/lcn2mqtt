"""Home Assistant MQTT Discovery for LCN modules."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiomqtt
from pypck.lcn_addr import LcnAddr

from .. import __version__
from ..config import AppConfig
from ..module import Module

_LOG = logging.getLogger(__name__)


class DiscoveryPublisher:
    """Publishes HA MQTT device-discovery messages for LCN modules."""

    def __init__(self, config: AppConfig, mqtt: aiomqtt.Client) -> None:
        self._config = config
        self._mqtt = mqtt

    # ---------- helpers ----------

    def _bridge_identifier(self) -> str:
        return f"{self._config.mqtt.base_topic}_bridge"

    def _addr_prefix(self, addr: LcnAddr) -> str:
        device = "group" if addr.is_group else "module"
        return (
            f"{self._config.mqtt.base_topic}/{device}/{addr.seg_id:d}/{addr.addr_id:d}"
        )

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
        prefix = self._config.homeassistant.prefix
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

    def _output_components(self, lcn_addr: LcnAddr) -> dict[str, Any]:
        prefix = self._addr_prefix(lcn_addr)
        addr_str = lcn_addr.to_string()
        cmps: dict[str, Any] = {}
        for i in range(1, 5):
            uid = f"{self._config.mqtt.base_topic}_{addr_str}_output{i}"
            cmps[uid] = {
                "platform": "light",
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

    def _relay_components(self, lcn_addr: LcnAddr) -> dict[str, Any]:
        prefix = self._addr_prefix(lcn_addr)
        addr_str = lcn_addr.to_string()
        cmps: dict[str, Any] = {}
        for i in range(1, 9):
            uid = f"{self._config.mqtt.base_topic}_{addr_str}_relay{i}"
            cmps[uid] = {
                "platform": "switch",
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

    def _motor_components(self, lcn_addr: LcnAddr) -> dict[str, Any]:
        prefix = self._addr_prefix(lcn_addr)
        addr_str = lcn_addr.to_string()
        cmps: dict[str, Any] = {}
        for i in range(1, 5):
            uid = f"{self._config.mqtt.base_topic}_{addr_str}_motor{i}"
            cmps[uid] = {
                "platform": "cover",
                "unique_id": uid,
                "name": f"Motor {i}",
                "state_topic": f"{prefix}/motor_relays/{i}/state",
                "value_template": "{{ value_json.state }}",
                "command_topic": f"{prefix}/motor_relays/{i}/set",
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

    async def publish_module(self, lcn_addr: LcnAddr, module: Module) -> None:
        """Publish a device-discovery entry for one LCN module."""
        addr_str = lcn_addr.to_string()
        display_name = module.name.strip() if module.name else f"LCN {addr_str.upper()}"
        cmps: dict[str, Any] = {}
        cmps.update(self._output_components(lcn_addr))
        cmps.update(self._relay_components(lcn_addr))
        cmps.update(self._motor_components(lcn_addr))
        await self._publish_device(
            f"{self._config.mqtt.base_topic}_{addr_str}",
            {
                "dev": {
                    "identifiers": [f"{self._config.mqtt.base_topic}_{addr_str}"],
                    "name": display_name,
                    "manufacturer": "Issendorff",
                    "model": module.serials.type.description,
                    "serial_number": f"0x{module.serials.hardware:02X}",
                    "sw_version": f"0x{module.serials.software:02X}",
                    "hw_version": addr_str,
                    "via_device": self._bridge_identifier(),
                },
                "availability": self._availability(),
                "components": cmps,
            },
        )
        _LOG.info("Discovery: module published: %s", addr_str)

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
                    "name": f"LCN2MQTT Bridge ({base})",
                    "manufacturer": "lcn2mqtt",
                    "model": "LCN2MQTT Bridge",
                },
                "availability": self._availability(),
                "components": {
                    status_uid: {
                        "platform": "sensor",
                        "unique_id": status_uid,
                        "name": "Status",
                        "state_topic": f"{base}/bridge/status",
                    }
                },
            },
        )
        _LOG.info("Discovery: bridge published")

    async def publish_modules(self, modules: dict[LcnAddr, Module]) -> None:
        """Scan LCN modules (optional) and publish module discovery entries."""
        for lcn_addr, module in modules.items():
            if lcn_addr.is_group:
                continue
            await self.publish_module(lcn_addr, module)
