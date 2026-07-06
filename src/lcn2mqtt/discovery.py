"""Home Assistant MQTT Discovery for LCN modules."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiomqtt
from pypck.lcn_addr import LcnAddr

from lcn2mqtt import __version__

from .models.config import AppConfig, DeviceConfig

_LOG = logging.getLogger(__name__)

OUTPUTS = {"output1", "output2", "output3", "output4"}
RELAYS = {
    "relay1",
    "relay2",
    "relay3",
    "relay4",
    "relay5",
    "relay6",
    "relay7",
    "relay8",
}
MOTORS = {"motor1", "motor2", "motor3", "motor4"}
LEDS = {
    "led1",
    "led2",
    "led3",
    "led4",
    "led5",
    "led6",
    "led7",
    "led8",
    "led9",
    "led10",
    "led11",
    "led12",
}

STANDARD_COMPONENTS = OUTPUTS | RELAYS


class DiscoveryManager:
    """Handles HA MQTT device-discovery messages for LCN modules."""

    def __init__(self, config: AppConfig, mqtt: aiomqtt.Client) -> None:
        """Initialize the DiscoveryManager with the application configuration and MQTT client."""
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

    def _parse_addr_from_topic(self, topic: str) -> LcnAddr:
        """Parse the segment, address, and group flag from an MQTT topic, or return None if it can't be parsed."""
        parts = topic.lower().split("/")

        # expected topic format: <base>/<m|g>/<seg>/<addr>/<handler>/<subtopics...>
        try:
            is_group = parts[1] == "group"
            seg = int(parts[2])
            addr = int(parts[3])
        except (IndexError, ValueError) as exc:
            raise ValueError("Topic does not match expected format") from exc
        return LcnAddr(seg, addr, is_group)

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
            payload="",
            qos=self._config.mqtt.qos,
            retain=True,
        )  # publish empty payload to clear retained message first

        await self._mqtt.publish(
            topic,
            payload=json.dumps(payload),
            qos=self._config.mqtt.qos,
            retain=True,
        )
        _LOG.debug("Discovery published: %s", topic)

    # ---------- public API ----------

    async def publish_module(self, lcn_addr: LcnAddr, module: DeviceConfig) -> None:
        """Publish a device-discovery entry for one LCN module."""
        addr_str = lcn_addr.to_string()
        display_name = (
            f"LCN {addr_str.upper()}" if module.name is None else module.name.strip()
        )

        cmps: dict[str, Any] = {}

        if module.homeassistant is not None:
            for identifier, cmp in module.homeassistant.components.items():
                cmps[identifier] = cmp.discovery_info()

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

    async def publish_modules(self, modules: dict[LcnAddr, DeviceConfig]) -> None:
        """Scan LCN modules (optional) and publish module discovery entries."""
        for lcn_addr, module in modules.items():
            if lcn_addr.is_group:
                continue
            await self.publish_module(lcn_addr, module)
