"""Test for extra handlers."""

from typing import cast
from unittest.mock import AsyncMock

from lcn2mqtt.handlers.extra import handle_dyn_text_set, handle_pck_set
from lcn2mqtt.models.config import AppConfig
from lcn2mqtt.models.device import Device


class TestHandlePckSet:
    """Tests for the PCK set MQTT command handler."""

    async def test_handle_pck_set(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Test that handle_pck_set calls device_connection.pck with the correct payload."""
        payload = "PIN003"
        await handle_pck_set("pck/set", payload, module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.pck.assert_awaited_once_with(payload)


class TestHandleDynTextSet:
    """Tests for the dynamic text set MQTT command handler."""

    async def test_handle_dyn_text_set(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """Test that handle_dyn_text_set calls device_connection.dyn_text with the correct index and payload."""
        payload = "Hello"
        await handle_dyn_text_set("dyn_text/1/set", payload, module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.dyn_text.assert_awaited_once_with(0, payload)  # Index is 0-based

    async def test_out_of_range_index_is_ignored(
        self, module_with_conn: Device, config: AppConfig
    ) -> None:
        """A dyn_text index outside 1-4 is silently ignored."""
        await handle_dyn_text_set("dyn_text/5/set", "Hello", module_with_conn, config)
        conn = cast(AsyncMock, module_with_conn._device_connection)
        conn.dyn_text.assert_not_awaited()
