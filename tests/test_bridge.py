"""Tests for the Bridge class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lcn2mqtt.bridge import Bridge
from lcn2mqtt.models.module import Module
from pypck import lcn_defs
from pypck.inputs import ModSn
from pypck.lcn_addr import LcnAddr

# ---------------------------------------------------------------------------
# Topic helpers
# ---------------------------------------------------------------------------


class TestTopicHelpers:
    """Tests for the MQTT topic helper methods."""

    def test_base_topic(self, bridge: Bridge) -> None:
        """Base topic equals the configured identifier."""
        assert bridge._base_topic() == "lcntest"

    def test_addr_prefix_module(self, bridge: Bridge) -> None:
        """Module address prefix uses 'module' as the target type."""
        addr = LcnAddr(0, 7, False)
        assert bridge._addr_prefix(addr) == "lcntest/module/0/7"

    def test_addr_prefix_group(self, bridge: Bridge) -> None:
        """Group address prefix uses 'group' as the target type."""
        addr = LcnAddr(0, 3, True)
        assert bridge._addr_prefix(addr) == "lcntest/group/0/3"

    def test_bridge_status_topic(self, bridge: Bridge) -> None:
        """Bridge status topic is <base>/bridge/status."""
        assert bridge._bridge_status_topic() == "lcntest/bridge/status"

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
        existing = Module(address=addr)
        existing._device_connection = MagicMock()
        bridge_with_pchk.modules[addr] = existing
        bridge_with_pchk._pchk.get_device_connection = MagicMock(
            return_value=mock_device_conn
        )

        result = await bridge_with_pchk.ensure_module_complete(addr)
        assert result is existing

    async def test_new_module_auto_registered(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """Unknown module is auto-registered and its name fetched from the device."""
        addr = LcnAddr(0, 42, False)
        mock_device_conn.serials.hardware_serial = 100
        mock_device_conn.request_name = AsyncMock(return_value="NewModule")
        bridge_with_pchk._pchk.get_device_connection = MagicMock(
            return_value=mock_device_conn
        )

        result = await bridge_with_pchk.ensure_module_complete(addr)
        assert addr in bridge_with_pchk.modules
        assert result is bridge_with_pchk.modules[addr]
        assert result.name == "NewModule"

    async def test_module_name_stripped(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """Leading/trailing whitespace is stripped from the device name."""
        addr = LcnAddr(0, 10, False)
        mock_device_conn.request_name = AsyncMock(return_value="  Padded Name  ")
        bridge_with_pchk._pchk.get_device_connection = MagicMock(
            return_value=mock_device_conn
        )

        result = await bridge_with_pchk.ensure_module_complete(addr)
        assert result.name == "Padded Name"

    async def test_module_name_falls_back_when_request_fails(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """Address string is used as module name when request_name raises."""
        addr = LcnAddr(0, 11, False)
        mock_device_conn.request_name = AsyncMock(side_effect=Exception("timeout"))
        bridge_with_pchk._pchk.get_device_connection = MagicMock(
            return_value=mock_device_conn
        )

        result = await bridge_with_pchk.ensure_module_complete(addr)
        assert result.name == addr.to_string()

    async def test_discovery_published_for_new_module(
        self, bridge_with_pchk: Bridge, mock_device_conn: MagicMock
    ) -> None:
        """DiscoveryManager.publish_module is called when a new module is registered."""
        bridge_with_pchk._discovery = AsyncMock()
        bridge_with_pchk._discovery.publish_module = AsyncMock()
        addr = LcnAddr(0, 20, False)
        mock_device_conn.request_name = AsyncMock(return_value="Room")
        bridge_with_pchk._pchk.get_device_connection = MagicMock(
            return_value=mock_device_conn
        )

        await bridge_with_pchk.ensure_module_complete(addr)
        bridge_with_pchk._discovery.publish_module.assert_awaited_once()


# ---------------------------------------------------------------------------
# _set_module_serials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSetModuleSerials:
    """Tests for Bridge._set_module_serials."""

    async def test_serials_are_set(self, bridge: Bridge) -> None:
        """Hardware serial, software serial and manu are written to the module."""
        addr = LcnAddr(0, 7, False)
        module = Module(address=addr)

        inp = MagicMock(spec=ModSn)
        inp.hardware_serial = 12345
        inp.software_serial = 67890
        inp.manu = 1
        inp.hardware_type = lcn_defs.HardwareType.UNKNOWN

        await bridge._set_module_serials(module, inp)

        assert module.serials.hardware == 12345
        assert module.serials.software == 67890
        assert module.serials.manu == 1


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
        bridge.ensure_module_complete = AsyncMock()

        msg = self._make_msg("unrelated/topic", "payload")
        await bridge._handle_mqtt_message(msg)

        bridge.ensure_module_complete.assert_not_awaited()

    async def test_dispatches_command(self, bridge: Bridge) -> None:
        """A well-formed command topic is dispatched to dispatch_mqtt with the correct module."""
        bridge._mqtt = AsyncMock()
        addr = LcnAddr(0, 7, False)
        module = Module(address=addr)
        bridge.ensure_module_complete = AsyncMock(return_value=module)

        with patch(
            "lcn2mqtt.bridge.dispatch_mqtt", new_callable=AsyncMock
        ) as mock_dispatch:
            msg = self._make_msg("lcntest/module/0/7/output/1/set", "on")
            await bridge._handle_mqtt_message(msg)
            mock_dispatch.assert_awaited_once()
            assert mock_dispatch.call_args.kwargs["module"] is module

    async def test_payload_decoded_and_lowercased(self, bridge: Bridge) -> None:
        """Byte payloads are decoded to str and lower-cased before dispatch."""
        bridge._mqtt = AsyncMock()
        addr = LcnAddr(0, 7, False)
        module = Module(address=addr)
        bridge.ensure_module_complete = AsyncMock(return_value=module)

        with patch(
            "lcn2mqtt.bridge.dispatch_mqtt", new_callable=AsyncMock
        ) as mock_dispatch:
            msg = self._make_msg("lcntest/module/0/7/output/1/set", b"  ON  ")
            await bridge._handle_mqtt_message(msg)
            mock_dispatch.assert_awaited_once()
            assert mock_dispatch.call_args.args[1] == "on"

    async def test_invalid_topic_format_logged_as_warning(
        self, bridge: Bridge, caplog
    ) -> None:
        """An unparseable topic triggers a WARNING log entry."""
        import logging

        bridge._mqtt = AsyncMock()
        bridge.ensure_module_complete = AsyncMock()

        with caplog.at_level(logging.WARNING, logger="lcn2mqtt.bridge"):
            msg = self._make_msg("lcntest/notanumber/foo/bar/output1/set", "on")
            await bridge._handle_mqtt_message(msg)

        assert any("invalid topic" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# _dispatch_input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDispatchInput:
    """Tests for Bridge._dispatch_input."""

    async def test_mod_sn_calls_set_serials(self, bridge_with_pchk: Bridge) -> None:
        """ModSn inputs are routed to _set_module_serials instead of dispatch_input."""
        addr = LcnAddr(0, 7, False)
        module = Module(address=addr)
        bridge_with_pchk.ensure_module_complete = AsyncMock(return_value=module)
        bridge_with_pchk._set_module_serials = AsyncMock()

        inp = MagicMock(spec=ModSn)
        inp.physical_source_addr = addr

        await bridge_with_pchk._dispatch_input(inp)

        bridge_with_pchk._set_module_serials.assert_awaited_once_with(module, inp)

    async def test_regular_input_publishes_messages(
        self, bridge_with_pchk: Bridge
    ) -> None:
        """Messages yielded by dispatch_input are published to the module's MQTT prefix."""
        from lcn2mqtt.helpers import MqttMessage

        addr = LcnAddr(0, 7, False)
        module = Module(address=addr)
        bridge_with_pchk.ensure_module_complete = AsyncMock(return_value=module)
        bridge_with_pchk._publish = AsyncMock()

        inp = MagicMock()
        inp.physical_source_addr = addr

        async def fake_dispatch(inp, **kwargs):
            yield MqttMessage(topic="output/1/state", payload="on")

        with patch("lcn2mqtt.bridge.dispatch_input", side_effect=fake_dispatch):
            await bridge_with_pchk._dispatch_input(inp)

        bridge_with_pchk._publish.assert_awaited_once_with(
            f"{bridge_with_pchk._addr_prefix(addr)}/output/1/state", "on"
        )
