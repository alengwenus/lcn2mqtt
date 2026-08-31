"""Home Assistant discovery settings page (/homeassistant)."""

from __future__ import annotations

from nicegui import ui

from ..app import page_frame
from ..config_io import read_yaml, write_keys
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /homeassistant page with NiceGUI."""

    @ui.page("/homeassistant")
    def ha_page() -> None:
        page_frame(manager)
        cfg = read_yaml()
        d = cfg.get("homeassistant") or {}

        with ui.column().classes("w-full max-w-lg p-4 gap-4"):
            ui.label("Home Assistant Discovery").classes("text-h5")

            enabled = ui.switch(
                "Enable MQTT discovery",
                value=d.get("enabled", False),
            )
            prefix = ui.input(
                "Discovery prefix",
                value=d.get("prefix", "homeassistant"),
            ).classes("w-full")
            scan_modules = ui.switch(
                "Scan for modules on startup",
                value=d.get("scan_modules", True),
            )

            async def save() -> None:
                try:
                    write_keys(
                        {
                            "homeassistant": {
                                "enabled": enabled.value,
                                "prefix": prefix.value,
                                "scan_modules": scan_modules.value,
                            }
                        }
                    )
                    ui.notify("Saved", type="positive")
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Save", on_click=save, color="primary")
