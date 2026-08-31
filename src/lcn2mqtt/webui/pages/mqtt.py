"""MQTT connection settings page (/mqtt)."""

from __future__ import annotations

from typing import Any

from nicegui import ui
from pydantic import ValidationError

from lcn2mqtt.models.config import MqttConfig

from ..app import page_frame
from ..config_io import read_yaml, write_keys
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /mqtt page with NiceGUI."""

    @ui.page("/mqtt")
    def mqtt_page() -> None:
        banner = page_frame(manager)
        cfg = read_yaml()
        d = cfg.get("mqtt") or {}

        with ui.column().classes("w-full max-w-lg p-4 gap-4"):
            ui.label("MQTT Connection").classes("text-h5")

            base_topic = ui.input(
                "Base topic", value=d.get("base_topic", "lcn2mqtt")
            ).classes("w-full")
            host = ui.input("Host", value=d.get("host", "")).classes("w-full")
            port = ui.number(
                "Port", value=d.get("port", 1883), min=1, max=65535
            ).classes("w-full")
            username = ui.input("Username", value=d.get("username") or "").classes(
                "w-full"
            )
            password = ui.input(
                "Password",
                value=d.get("password") or "",
                password=True,
                password_toggle_button=True,
            ).classes("w-full")
            qos = ui.select(
                {
                    0: "0 – At most once",
                    1: "1 – At least once",
                    2: "2 – Exactly once",
                },
                label="QoS",
                value=d.get("qos", 0),
            ).classes("w-full")

            async def save() -> None:
                mqtt_dict: dict[str, Any] = {
                    "base_topic": base_topic.value,
                    "host": host.value,
                    "port": int(port.value or 1883),
                    "qos": qos.value,
                }
                if username.value:
                    mqtt_dict["username"] = username.value
                if password.value:
                    mqtt_dict["password"] = password.value
                try:
                    MqttConfig(**mqtt_dict)
                except ValidationError as exc:
                    ui.notify(exc.errors()[0]["msg"], type="negative")
                    return
                write_keys({"mqtt": mqtt_dict})
                manager.restart_needed = True
                banner.refresh()
                ui.notify("Saved", type="positive")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Save", on_click=save, color="primary")
