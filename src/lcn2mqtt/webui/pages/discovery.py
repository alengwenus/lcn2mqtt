"""Home Assistant per-device discovery configuration page (/discovery)."""

from __future__ import annotations

from typing import Any

import yaml
from nicegui import ui

from ..app import page_frame
from ..config_io import read_yaml, write_yaml
from ..helpers import device_title
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /discovery per-device page with NiceGUI."""

    @ui.page("/discovery")
    def discovery_page() -> None:
        banner = page_frame(manager)

        save_fns: list[Any] = []

        @ui.refreshable
        def device_list() -> None:
            save_fns.clear()
            cfg = read_yaml()
            devices: dict[str, Any] = cfg.get("devices") or {}

            if not devices:
                ui.label("No devices configured.").classes("text-grey-6 italic")
                return

            for addr_str, device_data in devices.items():
                _ha_device_card(manager, addr_str, device_data or {}, save_fns)

        async def save_all() -> None:
            for fn in save_fns:
                await fn()
            manager.restart_needed = True
            banner.refresh()

        with ui.column().classes("w-full p-4 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Home Assistant").classes("text-h5")
                ui.button("Save All", icon="save", on_click=save_all, color="primary")
            device_list()


def _ha_device_card(
    manager: BridgeManager,
    addr_str: str,
    device_data: dict[str, Any],
    save_fns: list[Any],
) -> None:
    """Render one device's Home Assistant configuration card."""
    ha_data = device_data.get("homeassistant") or {}
    inc_val = list(ha_data.get("include") or [])
    exc_val = list(ha_data.get("exclude") or [])

    with ui.expansion(
        device_title(manager, addr_str, device_data), icon="home"
    ).classes("w-full max-w-4xl border border-grey-3 rounded"):
        with ui.column().classes("w-full p-4 gap-4"):
            include_chips = ui.input_chips("Include", value=inc_val).classes("w-full")
            exclude_chips = ui.input_chips("Exclude", value=exc_val).classes("w-full")

            ui.separator()
            ui.label("Components (YAML)").classes("text-subtitle2")
            ui.markdown(
                "Define Home Assistant components "
                "(switches, lights, covers, climates, \u2026) as YAML. "
                "See the [configuration example]"
                "(https://github.com/alengwenus/lcn2mqtt)"
                " for the full format."
            ).classes("text-caption text-grey-7")

            ha_components = {
                k: v for k, v in ha_data.items() if k not in ("include", "exclude")
            }
            ha_yaml_str = (
                yaml.dump(
                    ha_components,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
                if ha_components
                else ""
            )
            ha_editor = (
                ui.textarea(label="Components", value=ha_yaml_str)
                .classes("w-full font-mono")
                .props("rows=12")
            )

        async def _save(a: str = addr_str) -> None:
            ha: dict[str, Any] = {}
            if include_chips.value:
                ha["include"] = list(include_chips.value)
            if exclude_chips.value:
                ha["exclude"] = list(exclude_chips.value)
            try:
                parsed = yaml.safe_load(ha_editor.value) or {}
                if not isinstance(parsed, dict):
                    raise TypeError("Components must be a YAML mapping")
                ha.update(parsed)
            except (yaml.YAMLError, TypeError) as exc:
                ui.notify(
                    f"Invalid YAML in components: {exc}",
                    type="negative",
                )
                return
            cfg = read_yaml()
            devs: dict[str, Any] = cfg.get("devices") or {}
            dev = dict(devs.get(a) or {})
            if ha:
                dev["homeassistant"] = ha
            else:
                dev.pop("homeassistant", None)
            devs[a] = dev
            cfg["devices"] = devs
            write_yaml(cfg)
            ui.notify(f"Saved HA config for {a}", type="positive")

        save_fns.append(_save)
