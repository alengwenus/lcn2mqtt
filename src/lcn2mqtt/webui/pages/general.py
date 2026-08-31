"""General settings page (/general)."""

from __future__ import annotations

from nicegui import ui

from ..app import page_frame
from ..config_io import read_yaml, write_keys
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /general page with NiceGUI."""

    @ui.page("/general")
    def general_page() -> None:
        banner = page_frame(manager)
        cfg = read_yaml()

        with ui.column().classes("w-full max-w-lg p-4 gap-4"):
            ui.label("General Settings").classes("text-h5")

            log_level = ui.select(
                ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                label="Log level",
                value=(cfg.get("log_level") or "INFO").upper(),
            ).classes("w-full")
            retained = ui.switch(
                "Retain broker states on restart",
                value=cfg.get("retained_broker_states", True),
            )

            async def save() -> None:
                try:
                    write_keys(
                        {
                            "log_level": log_level.value.lower(),
                            "retained_broker_states": retained.value,
                        }
                    )
                    manager.restart_needed = True
                    banner.refresh()
                    ui.notify("Saved", type="positive")
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Save", on_click=save, color="primary")
