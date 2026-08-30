"""LCN <-> MQTT bridge using pypck and aiomqtt."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

import aiomqtt
import pypck
from pypck import inputs, lcn_defs
from pypck.connection import PchkConnectionManager
from pypck.device import DeviceConnection
from pypck.lcn_addr import LcnAddr

from .discovery import DiscoveryManager
from .handlers.dispatcher import dispatch_input, dispatch_mqtt
from .helpers import MqttMessage, singleflight
from .models.config import AppConfig, DeviceConfig
from .models.device import ModuleSerials

_LOG = logging.getLogger(__name__)

LWT_PAYLOAD_ONLINE = "online"
LWT_PAYLOAD_OFFLINE = "offline"


class Bridge:
    """LCN <-> MQTT bridge."""

    _pchk: PchkConnectionManager
    _mqtt: aiomqtt.Client
    _loop_task: asyncio.Task[None]
    _tg_mqtt: asyncio.TaskGroup

    def __init__(self, config: AppConfig) -> None:
        """Initialize the Bridge with the application configuration."""
        self.config = config
        self.devices: dict[LcnAddr, DeviceConfig] = config.devices
        self._discovery: DiscoveryManager | None = None
        self._on_lcn_input_tasks: set[asyncio.Task[None]] = set()
        # Tracks pending deferred publish timers keyed by (LcnAddr, cancel_key).
        self._deferred_timers: dict[str, asyncio.Task[None]] = {}

    # ---------- topic helpers ----------

    @property
    def base_topic(self) -> str:
        """Return the base MQTT topic for this bridge."""
        return f"{self.config.mqtt.base_topic}"

    @property
    def bridge_status_topic(self) -> str:
        """MQTT topic for the bridge status."""
        return f"{self.base_topic}/bridge/status"

    def _parse_addr_from_topic(self, topic: str) -> LcnAddr:
        """Parse the segment, address, and group flag from an MQTT topic, or return None if it can't be parsed."""
        if not topic.startswith(self.base_topic + "/"):
            raise ValueError("Topic does not start with base topic")

        parts = topic.lower().split("/")

        # expected topic format: <base>/<m|g>/<seg>/<addr>/<handler>/<subtopics...>
        try:
            is_group = parts[1] == "group"
            seg = int(parts[2])
            addr = int(parts[3])
        except (IndexError, ValueError) as exc:
            raise ValueError("Topic does not match expected format") from exc
        return LcnAddr(seg, addr, is_group)

    # ---------- run ----------

    async def run(self) -> None:
        """Run the bridge."""
        async with AsyncExitStack() as stack:
            mqtt = await stack.enter_async_context(self._mqtt_client())
            pchk = await stack.enter_async_context(self._pchk_client())
            self._mqtt = mqtt
            self._pchk = pchk
            _LOG.info("Connected to LCN-PCHK at %s:%s", pchk.host, pchk.port)

            await mqtt.publish(
                self.bridge_status_topic,
                LWT_PAYLOAD_ONLINE,
                qos=self.config.mqtt.qos,
                retain=True,
            )

            if self.config.homeassistant.enabled:
                self._discovery = DiscoveryManager(self.config, mqtt)
                await self._discovery.publish_bridge()

            # Ensure all devices from config are created and complete before starting.
            for lcn_addr in self.devices:
                await self.ensure_device_complete(lcn_addr)

            if self.config.homeassistant.scan_modules:
                await self._discover_modules()

            pchk.register_for_inputs(self._on_lcn_input)

            await self._subscribe_command_topics(mqtt)

            async with asyncio.TaskGroup() as self._tg_mqtt:
                await self._mqtt_message_loop(mqtt)

    # ---------- MQTT ----------

    def _mqtt_client(self) -> aiomqtt.Client:
        """Create an MQTT client with the appropriate settings."""
        cfg = self.config.mqtt
        will = aiomqtt.Will(
            topic=self.bridge_status_topic,
            payload=LWT_PAYLOAD_OFFLINE,
            qos=cfg.qos,
            retain=True,
        )
        return aiomqtt.Client(
            transport=cfg.transport,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            identifier=f"{self.config.mqtt.base_topic}",
            tls_context=cfg.ssl_context,
            will=will,
        )

    async def _subscribe_command_topics(self, mqtt: aiomqtt.Client) -> None:
        """Subscribe to MQTT command topics."""
        lcn2mqtt_topic = f"{self.base_topic}/#"
        await mqtt.subscribe(lcn2mqtt_topic, qos=self.config.mqtt.qos)
        _LOG.info("Subscribed to %s", lcn2mqtt_topic)

        if self.config.homeassistant.enabled:
            prefix = self.config.homeassistant.prefix
            discovery_topic = f"{prefix}/device/+/config"
            await mqtt.subscribe(discovery_topic)
            _LOG.debug("Subscribed to discovery topic: %s", discovery_topic)

    async def _publish(self, topic: str, payload: Any, delay: float = 0.0) -> None:
        """Publish a message to an MQTT topic."""
        await asyncio.sleep(delay)
        await self._mqtt.publish(
            topic,
            payload=str(payload),
            qos=self.config.mqtt.qos,
            retain=True,
        )
        _LOG.debug("Dispatched: %s = %r", topic, payload)

    def publish(self, prefix: str, item: MqttMessage) -> None:
        """Publish a message to an MQTT topic, optionally deferring it."""
        key = f"{prefix}/{item.topic}"
        old = self._deferred_timers.pop(key, None)
        if old is not None:
            old.cancel()

        if item.delay is not None:
            self._deferred_timers[key] = asyncio.create_task(
                self._publish(
                    f"{self.base_topic}/{key}", item.payload, delay=item.delay
                )
            )

    async def _mqtt_message_loop(self, mqtt: aiomqtt.Client) -> None:
        """Loop to handle incoming MQTT messages."""
        async for msg in mqtt.messages:
            task = self._tg_mqtt.create_task(self._handle_mqtt_message(msg))
            task.add_done_callback(self._log_task_exception)

    def _log_task_exception(self, task: asyncio.Task[None]) -> None:
        """Log any exception raised while handling an MQTT message."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _LOG.exception("Failed to handle MQTT message", exc_info=exc)

    # ---------- LCN ----------

    def _pchk_client(self) -> pypck.connection.PchkConnectionManager:
        """Create an PCHK client with the appropriate settings."""
        cfg = self.config.lcn
        settings = {
            "ACKNOWLEDGE": cfg.acknowledge_commands,
            "SK_NUM_TRIES": cfg.sk_num_tries,
            "DIM_MODE": lcn_defs.OutputPortDimMode[cfg.dim_mode],
        }
        return pypck.connection.PchkConnectionManager(
            cfg.host, cfg.port, cfg.username, cfg.password, settings=settings
        )

    async def _get_device_connection(self, lcn_addr: LcnAddr) -> DeviceConnection:
        """Get the module connection for the given LCN address."""
        device_connection = self._pchk.get_device_connection(lcn_addr)
        await device_connection.serials_known()
        return device_connection

    @singleflight
    async def ensure_device_complete(self, lcn_addr: LcnAddr) -> DeviceConfig:
        """Ensure a Module exists for the given LCN address and return it."""
        publish: bool = False
        if lcn_addr not in self.devices:
            _LOG.info(
                "Auto-registering new LCN module %s",
                lcn_addr.to_string(),
            )
            self.devices[lcn_addr] = self.config.create_device_config(lcn_addr)
            publish = True

        device = self.devices[lcn_addr]

        # ensure we have a device_connection and serials for the module
        try:
            device_connection = device.device_connection
        except ValueError:
            # polls for module.serials automatically
            device_connection = await self._get_device_connection(lcn_addr)
            device.device_connection = device_connection

        if not lcn_addr.is_group:
            if device.serials.hardware == -1:
                device.serials = ModuleSerials(
                    hardware=device_connection.serials.hardware_serial,
                    software=device_connection.serials.software_serial,
                    manu=device_connection.serials.manu,
                    type=device_connection.serials.hardware_type,
                )
                publish = True

        if device.name is None:
            if lcn_addr.is_group:
                device.name = f"LCN Group ({lcn_addr.to_string().upper()})"
            else:
                device.name = await device_connection.request_name()
            publish = True

        if self._discovery is not None and publish:
            await self._discovery.publish_device(lcn_addr, device)

        return device

    async def _discover_modules(self) -> None:
        """Discover modules on the LCN bus and populate the modules dictionary."""
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
            await self.ensure_device_complete(lcn_addr)

    # ---------- LCN -> MQTT ----------

    def _on_lcn_input(self, inp: inputs.Input) -> None:
        """Schedules async dispatch from incoming LCN inputs."""
        # Schedule async dispatch; pypck calls this from the event loop.
        task = asyncio.create_task(self._dispatch_input(inp))
        self._on_lcn_input_tasks.add(task)
        task.add_done_callback(self._on_lcn_input_tasks.discard)

    async def _dispatch_input(self, inp: inputs.Input) -> None:
        """Dispatch an incoming LCN input to the appropriate handler and MQTT topic."""
        try:
            physical_source_address = getattr(inp, "physical_source_addr", None)
            if physical_source_address is None:
                return
            lcn_addr: LcnAddr = self._pchk.physical_to_logical(physical_source_address)

            device = await self.ensure_device_complete(
                lcn_addr
            )  # ensure module exists and is complete before handling input

            if isinstance(inp, inputs.ModInput):
                dispatch_input(inp, device=device, bridge=self)
            # _LOG.debug("Unhandled LCN input: %s", type(inp).__name__)

        except Exception:  # noqa: BLE001
            _LOG.exception("Error dispatching LCN input %s", type(inp).__name__)

    # ---------- MQTT -> LCN ----------

    async def _handle_mqtt_message(self, msg: aiomqtt.Message) -> None:
        """Handle an incoming MQTT message."""
        topic = str(msg.topic).lower()
        if not topic.startswith(self.base_topic + "/"):
            return
        if topic.startswith(self.bridge_status_topic):
            return  # ignore bridge status messages

        # _LOG.debug("Received MQTT message: %s = %r", topic, msg.payload)
        try:
            # expected topic format: <base>/<module|group>/<seg>/<addr>/<handler>/<subtopics...>
            physical_source_address = self._parse_addr_from_topic(topic)
            logical_source_address = self._pchk.physical_to_logical(
                physical_source_address
            )
            subtopic = topic.split("/", 4)[-1]
        except Exception:  # noqa: BLE001
            _LOG.warning("Received MQTT message with invalid topic format: %s", topic)
            return

        payload = (
            msg.payload.decode("utf-8", errors="replace").strip()
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload).strip()
        )

        # normalize payload to lowercase for non-pck and non-dyn_text topics
        if subtopic not in (
            "pck/set",
            "dyn_text/1/set",
            "dyn_text/2/set",
            "dyn_text/3/set",
            "dyn_text/4/set",
        ):
            payload = payload.lower()

        # _LOG.debug("Received: %s = %r", topic, payload)

        device = await self.ensure_device_complete(
            logical_source_address
        )  # ensure module exists and is complete before handling input

        await dispatch_mqtt(subtopic, payload, device, self)
