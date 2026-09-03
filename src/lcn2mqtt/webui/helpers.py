"""Shared UI helpers for WebUI pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import BridgeManager


def device_title(
    manager: BridgeManager, addr_str: str, device_data: dict[str, Any]
) -> str:
    """Return an expansion title like 'name (M000.010)' for a device address string.

    Prefers the live name from the running bridge; falls back to the configured
    name; finally to the address itself.
    """
    addr_upper = addr_str.upper()
    name = (device_data.get("name") if device_data else None) or ""
    device = _lookup_live_device(manager, addr_str)
    if device is not None and device.name:
        name = device.name
    return f"{name} ({addr_upper})" if name else addr_upper


def _lookup_live_device(manager: BridgeManager, addr_str: str) -> Any:
    """Find the live device for an address string like 'm000010' or 'g000005'."""
    try:
        is_group = addr_str.lower().startswith("g")
        seg = int(addr_str[1:4])
        addr = int(addr_str[4:7])
    except (IndexError, ValueError):
        return None
    for lcn_addr, device in manager.devices.items():
        if (
            lcn_addr.seg_id == seg
            and lcn_addr.addr_id == addr
            and lcn_addr.is_group == is_group
        ):
            return device
    return None
