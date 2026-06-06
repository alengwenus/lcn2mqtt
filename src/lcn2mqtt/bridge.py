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
from .handlers import (
    LedHandler,
    MotorRelayHandler,
    OutputHandler,
    RelayHandler,
    VariableHandler,
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
        self._module_overrides = config.lcn.module_overrides
        self._output_handler = OutputHandler(self._publish)
        self._relay_handler = RelayHandler(self._publish)
        self._motor_relay_handler = MotorRelayHandler(self._publish)
        self._led_handler = LedHandler(self._publish)
        self._variable_handler = VariableHandler(self._publish)

    # ---------- topic helpers ----------

    def _base_topic(self) -> str:
        """Base MQTT topic for this bridge."""
        return f"{self.config.mqtt.base_topic}"

    def _addr_prefix(self, lcn_addr: LcnAddr) -> str:
        """MQTT topic prefix for the given LCN address."""
        kind = "g" if lcn_addr.is_group else "m"
        return f"{self._base_topic()}/{kind}{lcn_addr.seg_id:03d}{lcn_addr.addr_id:03d}"

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

            self._pchk = await self._connect_lcn()
            stack.push_async_callback(self._pchk.async_close)

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
        topic = f"{self._base_topic()}/+/#"
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

    async def _handle_mqtt_message(self, msg: aiomqtt.Message) -> None:
        """Handle an incoming MQTT message."""
        topic = str(msg.topic)
        base = self._base_topic()
        if not topic.startswith(base + "/"):
            return
        rest = topic[len(base) + 1 :]
        parts = rest.split("/")
        # expected: <addr>/<handler>/...
        if len(parts) < 2:
            return
        addr_s, handler = parts[0], parts[1]
        sub_parts = parts[2:]
        try:
            seg = int(addr_s[1:4])
            addr = int(addr_s[4:])  # skip m/g
            is_group = addr_s[0] == "g"  # noqa: F841
        except ValueError:
            return

        payload = (
            msg.payload.decode("utf-8", errors="replace").strip().lower()
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload).strip().lower()
        )
        # _LOG.debug("Received: %s = %r", topic, payload)

        lcn_addr = LcnAddr(seg, addr, False)
        if lcn_addr not in self.modules:
            _LOG.info("Auto-registering new LCN module %s.%s via command", seg, addr)
            self.modules[lcn_addr] = self._create_module(lcn_addr)

        module_conn = self._get_module_connection(seg, addr)
        if module_conn is None:
            return

        module = self.modules[lcn_addr]
        if handler == "output":
            await self._output_handler.handle_command(
                module_conn, handler, sub_parts, payload, module
            )
        elif handler == "relay":
            await self._relay_handler.handle_command(
                module_conn,
                handler,
                sub_parts,
                payload,
            )
        elif handler == "motor_relays":
            await self._motor_relay_handler.handle_command(
                module_conn, handler, sub_parts, payload
            )
        elif handler in ["variable"]:
            pass
        else:
            _LOG.debug("Ignoring command handler %s", handler)

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

    def _get_module_connection(self, seg: int, addr: int):
        """Get the module connection for the given segment and address."""
        if self._pchk is None:
            return None
        lcn_addr = LcnAddr(seg, addr, False)
        return self._pchk.get_device_connection(lcn_addr)

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
        overrides = self._module_overrides.get(
            (lcn_addr.seg_id, lcn_addr.addr_id, lcn_addr.is_group), {}
        )
        for field_path, value in overrides.items():
            try:
                Bridge._set_nested_attr(module, field_path.split("."), value)
                _LOG.debug(
                    "Applied override %03d.%s%03d %s=%r",
                    lcn_addr.seg_id,
                    "g" if lcn_addr.is_group else "m",
                    lcn_addr.addr_id,
                    field_path,
                    value,
                )
            except Exception:  # noqa: BLE001
                _LOG.warning(
                    "Ignoring invalid override for %03d.%s%03d %s=%r",
                    lcn_addr.seg_id,
                    "g" if lcn_addr.is_group else "m",
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
            if lcn_addr not in self.modules:
                _LOG.info(
                    "Auto-registering new LCN module %s.%s",
                    lcn_addr.seg_id,
                    lcn_addr.addr_id,
                )
                self.modules[lcn_addr] = self._create_module(lcn_addr)
            module = self.modules[lcn_addr]
            prefix = self._addr_prefix(lcn_addr)

            if isinstance(inp, inputs.ModSn):
                await self._set_module_serials(module, inp)
            elif isinstance(inp, inputs.ModStatusOutput):
                await self._output_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusRelays):
                await self._relay_handler.handle_input(inp, module, prefix)
                await self._motor_relay_handler.handle_input(inp, module, prefix)
            # elif isinstance(inp, inputs.ModStatusLedsAndLogicOps):
            #     await self._led_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusVar):
                await self._variable_handler.handle_input(inp, module, prefix)
            else:
                _LOG.debug("Unhandled LCN input: %s", type(inp).__name__)

        except Exception:  # noqa: BLE001
            _LOG.exception("Error dispatching LCN input %s", type(inp).__name__)

    async def _set_module_serials(self, module: Module, inp: inputs.ModSn) -> None:
        """Set the serial numbers and type for a module based on a ModSn input."""
        module.serials.hardware = inp.hardware_serial
        module.serials.software = inp.software_serial
        module.serials.manu = inp.manu
        module.serials.type = inp.hardware_type

    # ---------- MQTT -> LCN ----------
