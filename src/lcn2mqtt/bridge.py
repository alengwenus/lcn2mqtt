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
    MotorHandler,
    OutputHandler,
    RelayHandler,
    VariableHandler,
)
from .models import Module

_LOG = logging.getLogger(__name__)

LWT_PAYLOAD_ONLINE = "online"
LWT_PAYLOAD_OFFLINE = "offline"


class Bridge:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.modules: dict[LcnAddr, Module] = {}
        self._pchk: PchkConnectionManager | None = None
        self._mqtt: aiomqtt.Client | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._output_handler = OutputHandler(self._publish)
        self._relay_handler = RelayHandler(self._publish)
        self._motor_handler = MotorHandler(self._publish)
        self._led_handler = LedHandler(self._publish)
        self._variable_handler = VariableHandler(self._publish)

    # ---------- topic helpers ----------

    def _base_topic(self) -> str:
        return f"lcn2mqtt/{self.config.lcn.name}"

    def _addr_prefix(self, lcn_addr: LcnAddr) -> str:
        kind = "g" if lcn_addr.is_group else "m"
        return (
            f"{self._base_topic()}/{lcn_addr.seg_id:03d}/{kind}{lcn_addr.addr_id:03d}"
        )

    def _bridge_status_topic(self) -> str:
        return f"{self._base_topic()}/bridge/status"

    # ---------- run ----------

    async def run(self) -> None:
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
            identifier=f"lcn2mqtt.{self.config.lcn.name}",
            will=will,
        )

    async def _subscribe_command_topics(self, mqtt: aiomqtt.Client) -> None:
        # Wildcard subscription for all commands
        topic = f"{self._base_topic()}/+/+/+/+/set"
        await mqtt.subscribe(topic, qos=self.config.mqtt.qos)
        _LOG.info("Subscribed to %s", topic)

    async def _publish(self, topic: str, payload: Any) -> None:
        if self._mqtt is None:
            return
        await self._mqtt.publish(
            topic,
            payload=str(payload),
            qos=self.config.mqtt.qos,
            retain=True,
        )

    async def _mqtt_message_loop(self, mqtt: aiomqtt.Client) -> None:
        async for msg in mqtt.messages:
            try:
                await self._handle_mqtt_message(msg)
            except Exception:  # noqa: BLE001
                _LOG.exception("Failed to handle MQTT message %s", msg.topic)

    async def _handle_mqtt_message(self, msg: aiomqtt.Message) -> None:
        topic = str(msg.topic)
        base = self._base_topic()
        if not topic.startswith(base + "/"):
            return
        rest = topic[len(base) + 1 :]
        parts = rest.split("/")
        # expected: <seg>/<addr>/<kind>/<index>/set
        if len(parts) != 5 or parts[-1] != "set":
            return
        seg_s, addr_s, kind, idx_s, _ = parts
        try:
            seg, addr, idx = int(seg_s), int(addr_s[1:]), int(idx_s)
        except ValueError:
            return

        payload = (
            msg.payload.decode("utf-8", errors="replace").strip().lower()
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload).strip().lower()
        )
        _LOG.debug("Cmd %s/%s/%s/%s = %r", seg, addr, kind, idx, payload)

        lcn_addr = LcnAddr(seg, addr, False)
        if lcn_addr not in self.modules:
            _LOG.info("Auto-registering new LCN module %s.%s via command", seg, addr)
            self.modules[lcn_addr] = Module()

        module_conn = self._get_module_connection(seg, addr)
        if module_conn is None:
            return

        if kind == "output":
            await self._output_handler.handle_command(module_conn, idx, payload)
        elif kind == "relay":
            await self._relay_handler.handle_command(module_conn, idx, payload)
        elif kind == "motor":
            await self._motor_handler.handle_command(module_conn, idx, payload)
        else:
            _LOG.debug("Ignoring command kind %s", kind)

    # ---------- LCN ----------

    async def _connect_lcn(self) -> PchkConnectionManager:
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
        if self._pchk is None:
            return None
        lcn_addr = LcnAddr(seg, addr, False)
        return self._pchk.get_device_connection(lcn_addr)

    # ---------- LCN -> MQTT ----------

    def _on_lcn_input(self, inp: inputs.Input) -> None:
        # Schedule async dispatch; pypck calls this from the event loop.
        asyncio.create_task(self._dispatch_input(inp))

    async def _dispatch_input(self, inp: inputs.Input) -> None:
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
                self.modules[lcn_addr] = Module()
            module = self.modules[lcn_addr]
            prefix = self._addr_prefix(lcn_addr)

            if isinstance(inp, inputs.ModStatusOutput):
                await self._output_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusRelays):
                await self._relay_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusLedsAndLogicOps):
                await self._led_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusVar):
                await self._variable_handler.handle_input(inp, module, prefix)
            elif isinstance(inp, inputs.ModStatusMotorPositionBS4):
                await self._motor_handler.handle_input(inp, module, prefix)
            else:
                _LOG.debug("Unhandled LCN input: %s", type(inp).__name__)

        except Exception:  # noqa: BLE001
            _LOG.exception("Error dispatching LCN input %s", type(inp).__name__)

    # ---------- MQTT -> LCN ----------
