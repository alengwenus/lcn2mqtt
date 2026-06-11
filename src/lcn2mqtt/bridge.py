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

from .config import AppConfig
from .discovery import DiscoveryPublisher
from .handlers import (
    LedHandler,
    MotorRelayHandler,
    OutputHandler,
    RelayHandler,
    VariableHandler,
    SetpointHandler,
    ThresholdHandler,
)
from .models import Module

_LOG = logging.getLogger(__name__)

LWT_PAYLOAD_ONLINE = "online"
LWT_PAYLOAD_OFFLINE = "offline"


class Bridge:
    """LCN <-> MQTT bridge."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.modules: dict[LcnAddr, Module] = {}
        self._pchk: PchkConnectionManager | None = None
        self._mqtt: aiomqtt.Client | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._module_overrides = config.devices.module_overrides
        self._discovery: DiscoveryPublisher | None = None
        self._output_handler = OutputHandler(self._publish)
        self._relay_handler = RelayHandler(self._publish)
        self._motor_relay_handler = MotorRelayHandler(self._publish)
        self._led_handler = LedHandler(self._publish)
        self._variable_handler = VariableHandler(self._publish)
        self._setpoint_handler = SetpointHandler(self._publish)
        self._threshold_handler = ThresholdHandler(self._publish)

    # ---------- topic helpers ----------

    def _base_topic(self) -> str:
        """Base MQTT topic for this bridge."""
        return f"{self.config.mqtt.base_topic}"

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

            discovery: DiscoveryPublisher | None = None
            if self.config.homeassistant.enabled:
                discovery = DiscoveryPublisher(self.config, mqtt)
                self._discovery = discovery
                await discovery.publish_bridge()

            self._pchk = await self._connect_lcn()
            stack.push_async_callback(self._pchk.async_close)

            if discovery is not None:
                await discovery.publish_modules(self._pchk, self.modules)

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
            identifier=f"{self.config.mqtt.base_topic}",
            will=will,
        )

    async def _subscribe_command_topics(self, mqtt: aiomqtt.Client) -> None:
        """Subscribe to MQTT command topics."""
        topic = f"{self._base_topic()}/#"
        await mqtt.subscribe(topic, qos=self.config.mqtt.qos)
        _LOG.info("Subscribed to %s", topic)

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

    async def _get_device_connection(self, seg: int, addr: int):
        """Get the module connection for the given segment and address."""
        if self._pchk is None:
            return None
        lcn_addr = LcnAddr(seg, addr, False)
        device_connection = self._pchk.get_device_connection(lcn_addr)

        await device_connection.serials_known()
        if device_connection.serials.hardware_serial == -1:
            _LOG.warning(
                "Timeout waiting for serials of module %s.%s; several commands may not work",
                seg,
                addr,
            )
        return device_connection

    @staticmethod
    def _set_nested_attr(obj: object, parts: list[str], value: str) -> None:
        """Traverse *parts* on *obj* and set the final attribute to *value*."""
        if len(parts) == 1:
            setattr(obj, parts[0], value)
        else:
            Bridge._set_nested_attr(getattr(obj, parts[0]), parts[1:], value)

    def _create_module(self, lcn_addr: LcnAddr) -> Module:
        """Create a Module and apply any env-var overrides for this address."""
        module = Module()
        overrides = self._module_overrides.get(lcn_addr, {})
        for field_path, value in overrides.items():
            try:
                Bridge._set_nested_attr(module, field_path.split("."), value)
                _LOG.info(
                    "Applied override %s%03d%03d.%s=%r",
                    "g" if lcn_addr.is_group else "m",
                    lcn_addr.seg_id,
                    lcn_addr.addr_id,
                    field_path,
                    value,
                )
            except Exception:  # noqa: BLE001
                _LOG.warning(
                    "Ignoring invalid override for %s%03d%03d.%s=%r",
                    "g" if lcn_addr.is_group else "m",
                    lcn_addr.seg_id,
                    lcn_addr.addr_id,
                    field_path,
                    value,
                )
        return module

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
            is_new = lcn_addr not in self.modules
            if is_new:
                _LOG.info(
                    "Auto-registering new LCN module %s.%s",
                    lcn_addr.seg_id,
                    lcn_addr.addr_id,
                )
                self.modules[lcn_addr] = self._create_module(lcn_addr)

            device_connection = await self._get_device_connection(
                lcn_addr.seg_id, lcn_addr.addr_id
            )
            if device_connection is None:
                return

            module = self.modules[lcn_addr]
            prefix = self._addr_prefix(lcn_addr)

            if is_new and self._discovery is not None:
                try:
                    name = await device_connection.request_name()
                    if name:
                        module.name = name.strip()
                except Exception:  # noqa: BLE001
                    _LOG.debug("Discovery: could not fetch name for %s", lcn_addr)
                await self._discovery.publish_module(lcn_addr, module)

            if isinstance(inp, inputs.ModSn):
                await self._set_module_serials(module, inp)
            elif isinstance(inp, inputs.ModStatusOutput):
                await self._output_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusRelays):
                await self._relay_handler.handle_input(inp, module, prefix)
                await self._motor_relay_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusLedsAndLogicOps):
                await self._led_handler.handle_input(inp, module, prefix)
            #     await self._led_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusVar):
                await self._variable_handler.handle_input(inp, module, prefix)
                await self._setpoint_handler.handle_input(inp, module, prefix)
                await self._threshold_handler.handle_input(inp, module, prefix)
            else:
                pass
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
            # expected topic format: <base>/<m|g>/<seg>/<addr>/<handler>/<subtopics...>
            lcn_addr = self._parse_addr_from_topic(topic)
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

        is_new = lcn_addr not in self.modules
        if is_new:
            _LOG.info(
                "Auto-registering new LCN module %s.%s via command",
                lcn_addr.seg_id,
                lcn_addr.addr_id,
            )
            self.modules[lcn_addr] = self._create_module(lcn_addr)

        device_connection = await self._get_device_connection(
            lcn_addr.seg_id, lcn_addr.addr_id
        )
        if device_connection is None:
            return

        module = self.modules[lcn_addr]
        if is_new and self._discovery is not None:
            try:
                name = await device_connection.request_name()
                if name:
                    module.name = name.strip()
            except Exception:  # noqa: BLE001
                _LOG.debug("Discovery: could not fetch name for %s", lcn_addr)
            await self._discovery.publish_module(lcn_addr, module)

        if handler == "output":
            await self._output_handler.handle_command(
                device_connection, handler, sub_parts, payload, module
            )
        elif handler == "relay":
            await self._relay_handler.handle_command(
                device_connection,
                handler,
                sub_parts,
                payload,
            )
        elif handler == "motor_relays":
            await self._motor_relay_handler.handle_command(
                device_connection, handler, sub_parts, payload
            )
        elif handler == "variable":
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
        else:
            _LOG.debug("Ignoring command handler %s", handler)
