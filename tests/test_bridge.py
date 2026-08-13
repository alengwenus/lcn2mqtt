"""Tests for the Bridge class."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pypck import inputs, lcn_defs
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.config import DeviceConfig
from lcn2mqtt.models.device import Device

# ---------------------------------------------------------------------------
# Topic helpers
# ---------------------------------------------------------------------------


class TestTopicHelpers:
    """Tests for the MQTT topic helper methods."""

    def test_base_topic(self, bridge: Bridge) -> None:
        """Base topic equals the configured identifier."""
        assert bridge.base_topic == "lcntest"

    def test_bridge_status_topic(self, bridge: Bridge) -> None:
        """Bridge status topic is <base>/bridge/status."""
        assert bridge.bridge_status_topic == "lcntest/bridge/status"

    def test_parse_addr_module(self, bridge: Bridge) -> None:
        """Module address is correctly parsed from a topic string."""
        addr = bridge._parse_addr_from_topic("lcntest/module/0/7/output/1/set")
        assert addr.seg_id == 0
        assert addr.addr_id == 7
        assert not addr.is_group

    def test_parse_addr_group(self, bridge: Bridge) -> None:
        """Group address is correctly parsed from a topic string."""
        addr = bridge._parse_addr_from_topic("lcntest/group/0/5/relay/1/set")
        assert addr.seg_id == 0
        assert addr.addr_id == 5
        assert addr.is_group

    def test_parse_addr_wrong_base_raises(self, bridge: Bridge) -> None:
        """ValueError is raised when the topic does not start with the base topic."""
        with pytest.raises(ValueError, match="base topic"):
            bridge._parse_addr_from_topic("other/module/0/7/output/1/set")

    def test_parse_addr_malformed_raises(self, bridge: Bridge) -> None:
        """ValueError is raised when segment or address parts are not integers."""
        with pytest.raises(ValueError):
            bridge._parse_addr_from_topic("lcntest/module/notanint/7/output/1/set")


# ---------------------------------------------------------------------------
# ensure_module_complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsureModuleComplete:
    """Tests for Bridge.ensure_module_complete."""

    async def test_existing_module_returned(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """Already-registered module is returned without re-creating it."""
        addr = LcnAddr(0, 7, False)
        existing = DeviceConfig(address=addr)
        existing.device_connection = mock_device_conn
        bridge_with_pchk.devices[addr] = existing
        result = await bridge_with_pchk.ensure_device_complete(addr)
        assert result is existing

    async def test_new_module_auto_registered(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """Unknown module is auto-registered and its name fetched from the device."""
        addr = LcnAddr(0, 42, False)
        mock_device_conn.serials.hardware_serial = 100
        mock_device_conn.request_name = AsyncMock(return_value="NewModule")
        with patch.object(
            bridge_with_pchk._pchk,
            "get_device_connection",
            MagicMock(return_value=mock_device_conn),
        ):
            result = await bridge_with_pchk.ensure_device_complete(addr)
        assert addr in bridge_with_pchk.devices
        assert result is bridge_with_pchk.devices[addr]
        assert result.name == "NewModule"

    async def test_module_name_falls_back_when_request_fails(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """None is used as module name when request_name returns None."""
        addr = LcnAddr(0, 11, False)
        mock_device_conn.request_name = AsyncMock(return_value=None)
        with patch.object(
            bridge_with_pchk._pchk,
            "get_device_connection",
            MagicMock(return_value=mock_device_conn),
        ):
            result = await bridge_with_pchk.ensure_device_complete(addr)
        assert result.name is None

    async def test_discovery_published_for_new_module(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """DiscoveryManager.publish_device is called when a new module is registered."""
        bridge_with_pchk._discovery = AsyncMock()
        bridge_with_pchk._discovery.publish_device = AsyncMock()
        addr = LcnAddr(0, 20, False)
        mock_device_conn.request_name = AsyncMock(return_value="Room")
        with patch.object(
            bridge_with_pchk._pchk,
            "get_device_connection",
            MagicMock(return_value=mock_device_conn),
        ):
            await bridge_with_pchk.ensure_device_complete(addr)
        bridge_with_pchk._discovery.publish_device.assert_awaited_once()


# ---------------------------------------------------------------------------
# _publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublish:
    """Tests for Bridge._publish."""

    async def test_publish_calls_mqtt(self, bridge: Bridge) -> None:
        """MQTT client publish is called with the correct topic, payload, QoS and retain flag."""
        bridge._mqtt = AsyncMock()
        bridge._mqtt.publish = AsyncMock()

        await bridge._publish("lcntest/module/0/7/output/1/state", "on")

        bridge._mqtt.publish.assert_awaited_once_with(
            "lcntest/module/0/7/output/1/state",
            payload="on",
            qos=bridge.config.mqtt.qos,
            retain=True,
        )

    async def test_publish_converts_payload_to_str(self, bridge: Bridge) -> None:
        """Non-string payloads are converted to str before publishing."""
        bridge._mqtt = AsyncMock()
        bridge._mqtt.publish = AsyncMock()

        await bridge._publish("some/topic", 42)

        _, kwargs = bridge._mqtt.publish.call_args
        assert kwargs["payload"] == "42"


# ---------------------------------------------------------------------------
# _handle_mqtt_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandleMqttMessage:
    """Tests for Bridge._handle_mqtt_message."""

    def _make_msg(self, topic: str, payload: str | bytes) -> MagicMock:
        msg = MagicMock()
        msg.topic = MagicMock()
        msg.topic.__str__ = MagicMock(return_value=topic)
        msg.payload = payload.encode() if isinstance(payload, str) else payload
        return msg

    async def test_ignores_unrelated_topic(self, bridge: Bridge) -> None:
        """Messages whose topic does not start with the base topic are silently ignored."""
        bridge._mqtt = AsyncMock()
        with patch.object(
            bridge, "ensure_device_complete"
        ) as mocked_ensure_device_complete:
            msg = self._make_msg("unrelated/topic", "payload")
            await bridge._handle_mqtt_message(msg)

            mocked_ensure_device_complete.assert_not_awaited()

    async def test_dispatches_command(self, bridge_with_pchk: Bridge) -> None:
        """A well-formed command topic is dispatched to dispatch_mqtt with the correct module."""
        bridge_with_pchk._mqtt = AsyncMock()
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)

        with (
            patch(
                "lcn2mqtt.bridge.dispatch_mqtt", new_callable=AsyncMock
            ) as mock_dispatch,
            patch.object(
                bridge_with_pchk,
                "ensure_device_complete",
                return_value=module,
            ),
        ):
            msg = self._make_msg("lcntest/module/0/7/output/1/set", "on")
            await bridge_with_pchk._handle_mqtt_message(msg)
            mock_dispatch.assert_awaited_once()
            assert mock_dispatch.call_args.args[2] is module

    async def test_payload_decoded_and_lowercased(
        self, bridge_with_pchk: Bridge
    ) -> None:
        """Byte payloads are decoded to str and lower-cased before dispatch."""
        bridge_with_pchk._mqtt = AsyncMock()
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)

        with (
            patch("lcn2mqtt.bridge.dispatch_mqtt") as mock_dispatch,
            patch.object(
                bridge_with_pchk,
                "ensure_device_complete",
                return_value=module,
            ),
        ):
            msg = self._make_msg("lcntest/module/0/7/output/1/set", b"  ON  ")
            await bridge_with_pchk._handle_mqtt_message(msg)
            mock_dispatch.assert_awaited_once()
            assert mock_dispatch.call_args.args[1] == "on"

    async def test_invalid_topic_format_logged_as_warning(
        self, bridge: Bridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unparsable topic triggers a WARNING log entry."""
        bridge._mqtt = AsyncMock()

        with (
            caplog.at_level(logging.WARNING, logger="lcn2mqtt.bridge"),
            patch.object(bridge, "ensure_device_complete"),
        ):
            msg = self._make_msg("lcntest/notanumber/foo/bar/output1/set", "on")
            await bridge._handle_mqtt_message(msg)

        assert any("invalid topic" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# _dispatch_input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDispatchInput:
    """Tests for Bridge._dispatch_input."""

    async def test_regular_input_publishes_messages(
        self, bridge_with_pchk: Bridge
    ) -> None:
        """Messages yielded by dispatch_input are published to the module's MQTT prefix."""
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)
        with (
            patch.object(
                bridge_with_pchk, "ensure_device_complete", return_value=module
            ),
            patch.object(bridge_with_pchk, "publish") as mock_publish,
        ):
            inp = inputs.ModStatusOutput(addr, output_id=0, percent=100)
            await bridge_with_pchk._dispatch_input(inp)

            mock_publish.assert_called_with(
                module.prefix,
                MqttMessage(topic="output/1/brightness", payload="100.00", delay=0.0),
            )

    async def test_deferred_message_from_dispatch_is_scheduled(
        self, bridge_with_pchk: Bridge
    ) -> None:
        """MqttMessage yielded by dispatch_input is registered in _deferred_timers."""
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)
        inp = inputs.ModStatusOutput(addr, output_id=0, percent=100)

        deferred = MqttMessage(
            topic="motor/outputs/state",
            payload="open",
            delay=10.0,
        )

        with patch.object(
            bridge_with_pchk, "ensure_device_complete", return_value=module
        ):
            await bridge_with_pchk._dispatch_input(inp)

        assert f"{module.prefix}/{deferred.topic}" in bridge_with_pchk._deferred_timers

    async def test_cancel_only_deferred_removes_existing_timer(
        self, bridge_with_pchk: Bridge
    ) -> None:
        """MqttMessage with delay=None cancels the existing timer and does not reschedule."""
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)
        module.motor_outputs.positioning_mode = lcn_defs.MotorPositioningMode.MODULE
        inp = inputs.ModStatusMotorPositionModule(addr, 3, position=100)

        mock_handle = MagicMock()
        bridge_with_pchk._deferred_timers[f"{module.prefix}/motor/outputs/state"] = (
            mock_handle
        )

        with patch.object(
            bridge_with_pchk, "ensure_device_complete", return_value=module
        ):
            await bridge_with_pchk._dispatch_input(inp)

        mock_handle.cancel.assert_called_once()
        assert (
            f"{module.prefix}/motor/outputs/state"
            not in bridge_with_pchk._deferred_timers
        )


# ---------------------------------------------------------------------------
# Deferred publish (_fire_deferred)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeferredMessages:
    """Tests for the generic deferred MQTT message mechanism."""

    async def test_fire_deferred_publishes_message(self, bridge: Bridge) -> None:
        """_fire_deferred publishes the given topic and payload."""
        bridge._mqtt = AsyncMock()
        prefix = "module/0/7"
        item = MqttMessage(
            topic="motor/outputs/state",
            payload="open",
            delay=0.01,
        )

        bridge.publish(prefix, item)
        await asyncio.sleep(0.1)

        bridge._mqtt.publish.assert_awaited_once()
        assert (
            bridge._mqtt.publish.call_args[0][0]
            == f"{bridge.base_topic}/{prefix}/motor/outputs/state"
        )
        assert bridge._mqtt.publish.call_args[1]["payload"] == "open"

    async def test_new_deferred_replaces_existing_timer(self, bridge: Bridge) -> None:
        """Dispatching a new MqttMessage for the same topic cancels the old timer."""
        bridge._mqtt = AsyncMock()
        addr = LcnAddr(0, 7, False)
        module = Device(address=addr)
        inp = MagicMock(spec=inputs.ModStatusOutput)
        inp.physical_source_addr = addr
        bridge._pchk = MagicMock()
        bridge._pchk.physical_to_logical = lambda a: a

        deferred = MqttMessage(topic="test/topic", payload="value", delay=10.0)
        bridge.publish(module.prefix, deferred)

        first_handle = bridge._deferred_timers.get(f"{module.prefix}/test/topic")
        assert first_handle is not None

        deferred2 = MqttMessage(topic="test/topic", payload="value2", delay=10.0)
        bridge.publish(module.prefix, deferred2)

        second_handle = bridge._deferred_timers.get(f"{module.prefix}/test/topic")
        assert second_handle is not None
        assert second_handle is not first_handle
        assert second_handle is not first_handle
