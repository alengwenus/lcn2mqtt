"""LCN <-> MQTT bridge using pypck and aiomqtt."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

import aiomqtt
from pypck import inputs, lcn_defs
from pypck.connection import PchkConnectionManager
from pypck.lcn_addr import LcnAddr

from .discovery import DiscoveryManager
from .handlers import (
    LedHandler,
    SetpointHandler,
    ThresholdHandler,
    VariableHandler,
)
from .handlers.dispatcher import dispatch_input, dispatch_mqtt
from .models.config import AppConfig
from .models.module import Module

_LOG = logging.getLogger(__name__)

LWT_PAYLOAD_ONLINE = "online"
LWT_PAYLOAD_OFFLINE = "offline"


class Bridge:
    """LCN <-> MQTT bridge."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.modules: dict[LcnAddr, Module] = config.devices
        self._pchk: PchkConnectionManager | None = None
        self._mqtt: aiomqtt.Client | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._discovery: DiscoveryManager | None = None
        self._led_handler = LedHandler(self._publish)
        self._variable_handler = VariableHandler(self._publish)
        self._setpoint_handler = SetpointHandler(self._publish)
        self._threshold_handler = ThresholdHandler(self._publish)

    # ---------- topic helpers ----------

    def _base_topic(self) -> str:
        """Base MQTT topic for this bridge."""
        return f"{self.config.mqtt.basetopic}"

    def _addr_prefix(self, lcn_addr: LcnAddr) -> str:
        """MQTT topic prefix for the given LCN address."""
        target_type = "group" if lcn_addr.is_group else "module"
        return (
            f"{self._base_topic()}/{target_type}/{lcn_addr.seg_id}/{lcn_addr.addr_id}"
        )

    def _parse_addr_from_topic(self, topic: str) -> LcnAddr:
        """Parse the segment, address, and group flag from an MQTT topic, or return None if it can't be parsed."""
        base = self._base_topic()
        if not topic.startswith(base + "/"):
            raise ValueError("Topic does not start with base topic")

        parts = topic.lower().split("/")

        # expected topic format: <base>/<m|g>/<seg>/<addr>/<handler>/<subtopics...>
        try:
            is_group = parts[1] == "group"
            seg = int(parts[2])
            addr = int(parts[3])
        except (IndexError, ValueError):
            raise ValueError("Topic does not match expected format")
        return LcnAddr(seg, addr, is_group)

    def _bridge_status_topic(self) -> str:
        """MQTT topic for the bridge status."""
        return f"{self._base_topic()}/bridge/status"

    # ---------- run ----------

    async def run(self) -> None:
        """Run the bridge."""
        async with AsyncExitStack() as stack:
            mqtt = await stack.enter_async_context(self._mqtt_client())
            self._mqtt = mqtt
            await mqtt.publish(
                self._bridge_status_topic(),
                LWT_PAYLOAD_ONLINE,
                qos=self.config.mqtt.qos,
                retain=True,
            )

            discovery: DiscoveryManager | None = None
            if self.config.homeassistant.enabled:
                discovery = DiscoveryManager(self.config, mqtt)
                self._discovery = discovery
                await discovery.publish_bridge()

            self._pchk = await self._connect_lcn()
            stack.push_async_callback(self._pchk.async_close)

            if self.config.homeassistant.scan_modules:
                await self._discover_modules()

            # Ensure all modules from config are created and complete before starting.
            for lcn_addr in self.modules:
                await self.ensure_module_complete(lcn_addr)

            await self._subscribe_command_topics(mqtt)

            await self._mqtt_message_loop(mqtt)

    # ---------- MQTT ----------

    def _mqtt_client(self) -> aiomqtt.Client:
        """Create an MQTT client with the appropriate settings."""
        cfg = self.config.mqtt
        will = aiomqtt.Will(
            topic=self._bridge_status_topic(),
            payload=LWT_PAYLOAD_OFFLINE,
            qos=cfg.qos,
            retain=True,
        )
        return aiomqtt.Client(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            identifier=f"{self.config.mqtt.basetopic}",
            will=will,
        )

    async def _subscribe_command_topics(self, mqtt: aiomqtt.Client) -> None:
        """Subscribe to MQTT command topics."""
        lcn2mqtt_topic = f"{self._base_topic()}/#"
        await mqtt.subscribe(lcn2mqtt_topic, qos=self.config.mqtt.qos)
        _LOG.info("Subscribed to %s", lcn2mqtt_topic)

        if self.config.homeassistant.enabled:
            prefix = self.config.homeassistant.prefix
            discovery_topic = f"{prefix}/device/+/config"
            await mqtt.subscribe(discovery_topic)
            _LOG.debug("Subscribed to discovery topic: %s", discovery_topic)

    async def _publish(self, topic: str, payload: Any) -> None:
        """Publish a message to an MQTT topic."""
        if self._mqtt is None:
            return
        await self._mqtt.publish(
            topic,
            payload=str(payload),
            qos=self.config.mqtt.qos,
            retain=True,
        )
        _LOG.debug("Dispatched: %s = %r", topic, payload)

    async def _mqtt_message_loop(self, mqtt: aiomqtt.Client) -> None:
        """Loop to handle incoming MQTT messages."""
        async for msg in mqtt.messages:
            try:
                await self._handle_mqtt_message(msg)
            except Exception:  # noqa: BLE001
                _LOG.exception("Failed to handle MQTT message %s", msg.topic)

    # ---------- LCN ----------

    async def _connect_lcn(self) -> PchkConnectionManager:
        """Connect to the LCN-PCHK and set up input handling."""
        cfg = self.config.lcn
        settings = {
            "ACKNOWLEDGE": cfg.acknowledge_commands,
            "SK_NUM_TRIES": cfg.sk_num_tries,
            "DIM_MODE": lcn_defs.OutputPortDimMode[cfg.dim_mode],
        }
        pchk = PchkConnectionManager(
            cfg.host, cfg.port, cfg.username, cfg.password, settings=settings
        )
        await pchk.async_connect()
        pchk.register_for_inputs(self._on_lcn_input)
        _LOG.info("Connected to LCN-PCHK at %s:%s", cfg.host, cfg.port)
        return pchk

    async def _get_device_connection(self, lcn_addr: LcnAddr):
        """Get the module connection for the given LCN address."""
        if self._pchk is None:
            return None
        device_connection = self._pchk.get_device_connection(lcn_addr)

        await device_connection.serials_known()
        if device_connection.serials.hardware_serial == -1:
            _LOG.warning(
                "Timeout waiting for serials of module %s.%s; several commands may not work",
                lcn_addr.seg_id,
                lcn_addr.addr_id,
            )
        return device_connection

    async def ensure_module_complete(self, lcn_addr: LcnAddr) -> Module:
        """Ensure a Module exists for the given LCN address and return it."""
        publish: bool = False
        if lcn_addr not in self.modules:
            _LOG.info(
                "Auto-registering new LCN module %s",
                lcn_addr.to_string(),
            )
            self.modules[lcn_addr] = self.config.create_device_config(lcn_addr)
            publish = True

        module = self.modules[lcn_addr]
        device_connection = await self._get_device_connection(lcn_addr)

        if module.device_connection is None:
            module.device_connection = device_connection
            publish = True

        if module.name == "" and device_connection is not None:
            try:
                module.name = lcn_addr.to_string()  # default name if request_name fails
                name = await device_connection.request_name()
                if name:
                    module.name = name.strip()
                publish = True
            except Exception:  # noqa: BLE001
                _LOG.debug("Discovery: could not fetch name for %s", lcn_addr)

        if self._discovery is not None and publish:
            await self._discovery.publish_module(lcn_addr, module)

        return module

    async def _discover_modules(self) -> None:
        """Discover modules on the LCN bus and populate the modules dictionary."""
        if self._pchk is None:
            return

        _LOG.info("Scanning LCN bus for modules …")
        await self._pchk.scan_modules()
        if not self._pchk.device_connections:
            _LOG.warning("No modules found on LCN bus")
            return

        _LOG.info(
            "Discovered %d module(s) on LCN bus",
            len(self._pchk.device_connections),
        )

        for lcn_addr in self._pchk.device_connections:
            await self.ensure_module_complete(lcn_addr)

    # ---------- LCN -> MQTT ----------

    def _on_lcn_input(self, inp: inputs.Input) -> None:
        """Callback for incoming LCN inputs; schedules async dispatch."""
        # Schedule async dispatch; pypck calls this from the event loop.
        asyncio.create_task(self._dispatch_input(inp))

    async def _dispatch_input(self, inp: inputs.Input) -> None:
        """Dispatch an incoming LCN input to the appropriate handler and MQTT topic."""
        try:
            lcn_addr: LcnAddr | None = getattr(inp, "physical_source_addr", None)
            if lcn_addr is None:
                return

            module = await self.ensure_module_complete(
                lcn_addr
            )  # ensure module exists and is complete before handling input
            prefix = self._addr_prefix(lcn_addr)

            if isinstance(inp, inputs.ModSn):
                await self._set_module_serials(module, inp)
            elif isinstance(inp, inputs.ModStatusLedsAndLogicOps):
                await self._led_handler.handle_input(inp, module, prefix)
            #     await self._led_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusVar):
                await self._variable_handler.handle_input(inp, module, prefix)
                await self._setpoint_handler.handle_input(inp, module, prefix)
                await self._threshold_handler.handle_input(inp, module, prefix)
            else:
                async for message in dispatch_input(inp, module=module):
                    await self._publish(f"{prefix}/{message.topic}", message.payload)
                # _LOG.debug("Unhandled LCN input: %s", type(inp).__name__)

        except Exception:  # noqa: BLE001
            _LOG.exception("Error dispatching LCN input %s", type(inp).__name__)

    async def _set_module_serials(self, module: Module, inp: inputs.ModSn) -> None:
        """Set the serial numbers and type for a module based on a ModSn input."""
        module.serials.hardware = inp.hardware_serial
        module.serials.software = inp.software_serial
        module.serials.manu = inp.manu
        module.serials.type = inp.hardware_type

    # ---------- MQTT -> LCN ----------

    async def _handle_mqtt_message(self, msg: aiomqtt.Message) -> None:
        """Handle an incoming MQTT message."""
        topic = str(msg.topic)
        base = self._base_topic()
        if not topic.startswith(base + "/"):
            return

        try:
            # expected topic format: <base>/<module|group>/<seg>/<addr>/<handler>/<subtopics...>
            lcn_addr = self._parse_addr_from_topic(topic)
            subtopic = topic.lower().split("/", 4)[-1]
            parts = topic.lower().split("/")
            handler = parts[4]
            sub_parts = parts[5:]
        except Exception:  # noqa: BLE001
            _LOG.warning("Received MQTT message with invalid topic format: %s", topic)
            return

        payload = (
            msg.payload.decode("utf-8", errors="replace").strip().lower()
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload).strip().lower()
        )
        # _LOG.debug("Received: %s = %r", topic, payload)

        module = await self.ensure_module_complete(
            lcn_addr
        )  # ensure module exists and is complete before handling input
        device_connection = module.device_connection

        await dispatch_mqtt(subtopic, payload, module=module)

        if handler == "variable":
            await self._variable_handler.handle_command(
                device_connection, handler, sub_parts, payload, module
            )
        elif handler == "setpoint":
            await self._setpoint_handler.handle_command(
                device_connection, handler, sub_parts, payload, module
            )
        elif handler == "threshold":
            await self._threshold_handler.handle_command(
                device_connection, handler, sub_parts, payload, module
            )
        elif handler == "led":
            await self._led_handler.handle_command(
                device_connection, handler, sub_parts, payload
            )
        # else:
        #     _LOG.debug("Ignoring command handler %s", handler)
