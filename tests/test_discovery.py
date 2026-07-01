"""Tests for the DiscoveryManager class."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.discovery import DiscoveryManager
from lcn2mqtt.models.config import AppConfig, DeviceConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mqtt() -> AsyncMock:
    """A mock aiomqtt Client."""
    client = AsyncMock()
    client.publish = AsyncMock()
    return client


@pytest.fixture
def manager(config: AppConfig, mqtt: AsyncMock) -> DiscoveryManager:
    """A DiscoveryManager backed by the test config and a mocked MQTT client."""
    return DiscoveryManager(config, mqtt)


@pytest.fixture
def module_addr() -> LcnAddr:
    return LcnAddr(0, 7, False)


@pytest.fixture
def device(module_addr: LcnAddr) -> DeviceConfig:
    """A minimal DeviceConfig with default serials."""
    dev = DeviceConfig(address=module_addr)
    dev.homeassistant.inject_base_topic("lcntest")
    return dev


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for DiscoveryManager helper methods."""

    def test_bridge_identifier(self, manager: DiscoveryManager) -> None:
        """Bridge identifier is <base_topic>_bridge."""
        assert manager._bridge_identifier() == "lcntest_bridge"

    def test_addr_prefix_module(
        self, manager: DiscoveryManager, module_addr: LcnAddr
    ) -> None:
        """Module prefix uses 'module' path segment."""
        assert manager._addr_prefix(module_addr) == "lcntest/module/0/7"

    def test_addr_prefix_group(self, manager: DiscoveryManager) -> None:
        """Group prefix uses 'group' path segment."""
        group_addr = LcnAddr(0, 3, True)
        assert manager._addr_prefix(group_addr) == "lcntest/group/0/3"

    def test_availability_payload(self, manager: DiscoveryManager) -> None:
        """Availability list references the bridge status topic."""
        avail = manager._availability()
        assert len(avail) == 1
        assert avail[0]["topic"] == "lcntest/bridge/status"
        assert avail[0]["payload_available"] == "online"
        assert avail[0]["payload_not_available"] == "offline"

    @pytest.mark.parametrize(
        "topic,expected_seg,expected_addr,expected_group",
        [
            ("lcntest/module/0/7/output/1/set", 0, 7, False),
            ("lcntest/group/1/5/relay/2/set", 1, 5, True),
        ],
    )
    def test_parse_addr_from_topic(
        self,
        manager: DiscoveryManager,
        topic: str,
        expected_seg: int,
        expected_addr: int,
        expected_group: bool,
    ) -> None:
        """Address is correctly parsed from valid topic strings."""
        addr = manager._parse_addr_from_topic(topic)
        assert addr.seg_id == expected_seg
        assert addr.addr_id == expected_addr
        assert addr.is_group == expected_group

    def test_parse_addr_malformed_raises(self, manager: DiscoveryManager) -> None:
        """ValueError is raised when the topic has non-integer segment/address."""
        with pytest.raises(ValueError):
            manager._parse_addr_from_topic("lcntest/module/notanint/7/output/1/set")

    def test_parse_addr_too_short_raises(self, manager: DiscoveryManager) -> None:
        """ValueError is raised when the topic is too short to parse."""
        with pytest.raises(ValueError):
            manager._parse_addr_from_topic("lcntest/module")


# ---------------------------------------------------------------------------
# publish_bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublishBridge:
    """Tests for DiscoveryManager.publish_bridge."""

    async def test_publishes_to_correct_topic(
        self, manager: DiscoveryManager, mqtt: AsyncMock
    ) -> None:
        """Bridge discovery is published to homeassistant/device/<bridge_id>/config."""
        await manager.publish_bridge()
        expected_topic = "homeassistant/device/lcntest_bridge/config"
        publish_calls = mqtt.publish.call_args_list
        # Two calls: one clear (empty) and one with payload
        assert len(publish_calls) == 2
        assert all(c.args[0] == expected_topic for c in publish_calls)

    async def test_clears_retained_message_first(
        self, manager: DiscoveryManager, mqtt: AsyncMock
    ) -> None:
        """First publish call sends an empty payload to clear retained messages."""
        await manager.publish_bridge()
        first_call = mqtt.publish.call_args_list[0]
        assert first_call.kwargs["payload"] == ""

    async def test_bridge_discovery_payload(
        self, manager: DiscoveryManager, mqtt: AsyncMock, snapshot
    ) -> None:
        """Bridge discovery payload matches the snapshot."""
        await manager.publish_bridge()
        second_call = mqtt.publish.call_args_list[1]
        payload = json.loads(second_call.kwargs["payload"])
        assert payload == snapshot

    async def test_publish_uses_retain(
        self, manager: DiscoveryManager, mqtt: AsyncMock
    ) -> None:
        """Both publish calls use retain=True."""
        await manager.publish_bridge()
        for c in mqtt.publish.call_args_list:
            assert c.kwargs["retain"] is True


# ---------------------------------------------------------------------------
# publish_module
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublishModule:
    """Tests for DiscoveryManager.publish_module."""

    async def test_clears_retained_message_first(
        self,
        manager: DiscoveryManager,
        mqtt: AsyncMock,
        module_addr: LcnAddr,
        device: DeviceConfig,
    ) -> None:
        """First publish call sends an empty payload to clear retained messages."""
        await manager.publish_module(module_addr, device)
        first_call = mqtt.publish.call_args_list[0]
        assert first_call.kwargs["payload"] == ""

    async def test_publishes_to_module_topic(
        self,
        manager: DiscoveryManager,
        mqtt: AsyncMock,
        module_addr: LcnAddr,
        device: DeviceConfig,
    ) -> None:
        """Module discovery is published to homeassistant/device/<module_id>/config."""
        await manager.publish_module(module_addr, device)
        addr_str = module_addr.to_string()
        expected_topic = f"homeassistant/device/lcntest_{addr_str}/config"
        topics = [c.args[0] for c in mqtt.publish.call_args_list]
        assert all(t == expected_topic for t in topics)

    async def test_module_discovery_payload(
        self,
        manager: DiscoveryManager,
        mqtt: AsyncMock,
        module_addr: LcnAddr,
        device: DeviceConfig,
        snapshot,
    ) -> None:
        """Module payload contains a 'dev' key with manufacturer and model."""
        await manager.publish_module(module_addr, device)
        second_call = mqtt.publish.call_args_list[1]
        payload = json.loads(second_call.kwargs["payload"])
        assert payload == snapshot


# ---------------------------------------------------------------------------
# publish_modules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublishModules:
    """Tests for DiscoveryManager.publish_modules."""

    async def test_groups_are_skipped(
        self, manager: DiscoveryManager, mqtt: AsyncMock
    ) -> None:
        """Group addresses are not published."""
        group_addr = LcnAddr(0, 3, True)
        module_addr = LcnAddr(0, 7, False)
        device = DeviceConfig(address=module_addr)
        device.homeassistant.inject_base_topic("lcntest")

        modules = {
            group_addr: DeviceConfig(address=group_addr),
            module_addr: device,
        }
        await manager.publish_modules(modules)

        # Only the module should produce publish calls (2 calls per module)
        assert mqtt.publish.call_count == 2

    async def test_all_modules_published(
        self, manager: DiscoveryManager, mqtt: AsyncMock
    ) -> None:
        """All non-group modules are published."""
        addrs = [LcnAddr(0, i, False) for i in range(3)]
        modules = {}
        for addr in addrs:
            dev = DeviceConfig(address=addr)
            dev.homeassistant.inject_base_topic("lcntest")
            modules[addr] = dev

        await manager.publish_modules(modules)
        # 2 publish calls per module (clear + payload)
        assert mqtt.publish.call_count == len(addrs) * 2
