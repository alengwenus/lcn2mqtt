"""LCN connection settings page (/lcn)."""

from __future__ import annotations

from nicegui import ui
from pydantic import ValidationError

from lcn2mqtt.models.config import LcnConfig

from ..app import page_frame
from ..config_io import read_yaml, write_keys
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /lcn page with NiceGUI."""

    @ui.page("/lcn")
    def lcn_page() -> None:
        banner = page_frame(manager)
        cfg = read_yaml()
        d = cfg.get("lcn") or {}

        with ui.column().classes("w-full max-w-lg p-4 gap-4"):
            ui.label("LCN Connection").classes("text-h5")

            host = ui.input("Host", value=d.get("host", "")).classes("w-full")
            port = ui.number(
                "Port", value=d.get("port", 4114), min=1, max=65535
            ).classes("w-full")
            username = ui.input("Username", value=d.get("username", "")).classes(
                "w-full"
            )
            password = ui.input(
                "Password",
                value=d.get("password", ""),
                password=True,
                password_toggle_button=True,
            ).classes("w-full")
            dim_mode = ui.select(
                ["STEPS50", "STEPS200"],
                label="Dim mode",
                value=(d.get("dim_mode") or "STEPS200").upper(),
            ).classes("w-full")
            sk_num_tries = ui.number(
                "SK num tries", value=d.get("sk_num_tries", 0), min=0
            ).classes("w-full")
            acknowledge = ui.switch(
                "Acknowledge commands",
                value=d.get("acknowledge_commands", False),
            )

            async def save() -> None:
                lcn_dict = {
                    "host": host.value,
                    "port": int(port.value or 4114),
                    "username": username.value,
                    "password": password.value,
                    "dim_mode": dim_mode.value,
                    "sk_num_tries": int(sk_num_tries.value or 0),
                    "acknowledge_commands": acknowledge.value,
                }
                try:
                    LcnConfig(**lcn_dict)
                except ValidationError as exc:
                    ui.notify(exc.errors()[0]["msg"], type="negative")
                    return
                write_keys({"lcn": lcn_dict})
                manager.restart_needed = True
                banner.refresh()
                ui.notify("Saved", type="positive")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Save", on_click=save, color="primary")
