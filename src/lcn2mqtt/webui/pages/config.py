"""Unified configuration page (/config) with tabs for each section."""

from __future__ import annotations

from typing import Any

from nicegui import ui
from pydantic import ValidationError

from lcn2mqtt.models.config import LcnConfig, MqttConfig

from ..app import page_frame
from ..config_io import get_env_overrides, read_yaml, write_keys
from ..manager import BridgeManager


def register(manager: BridgeManager) -> None:
    """Register the /config page with NiceGUI."""

    @ui.page("/config")
    def config_page() -> None:
        banner = page_frame(manager)
        cfg = read_yaml()
        env_overrides = get_env_overrides()

        ui.add_css(
            ".env-override .q-field__native { color: var(--q-warning) !important; }"
        )

        def _env_mark(element: Any, path: str) -> None:
            if path in env_overrides:
                val = env_overrides[path].replace("'", "")
                element.tooltip(f"\u26a0 Overridden by environment [{val}]")
                if isinstance(element, ui.select):
                    element.classes("env-override")
                elif isinstance(element, ui.switch):
                    element.props("color=warning")
                else:
                    element.props("input-class='text-warning'")

        with ui.column().classes("w-full max-w-lg p-4 gap-2"):
            # Controls are free variables resolved at call time, not here.
            async def save_all() -> None:
                try:
                    write_keys(
                        {
                            "log_level": log_level.value.lower(),
                            "retained_broker_states": retained.value,
                        }
                    )
                except Exception as exc:
                    ui.notify(str(exc), type="negative")
                    return

                lcn_dict = {
                    "host": lcn_host.value,
                    "port": int(lcn_port.value or 4114),
                    "username": lcn_username.value,
                    "password": lcn_password.value,
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

                mqtt_dict: dict[str, Any] = {
                    "base_topic": base_topic.value,
                    "host": mqtt_host.value,
                    "port": int(mqtt_port.value or 1883),
                    "qos": qos.value,
                }
                if mqtt_username.value:
                    mqtt_dict["username"] = mqtt_username.value
                if mqtt_password.value:
                    mqtt_dict["password"] = mqtt_password.value
                try:
                    MqttConfig(**mqtt_dict)
                except ValidationError as exc:
                    ui.notify(exc.errors()[0]["msg"], type="negative")
                    return
                write_keys({"mqtt": mqtt_dict})

                try:
                    write_keys(
                        {
                            "homeassistant": {
                                "enabled": ha_enabled.value,
                                "prefix": ha_prefix.value,
                                "scan_modules": ha_scan_modules.value,
                            }
                        }
                    )
                except Exception as exc:
                    ui.notify(str(exc), type="negative")
                    return

                manager.restart_needed = True
                banner.refresh()
                ui.notify("Saved", type="positive")

            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Configuration").classes("text-h5")
                ui.button("Save", on_click=save_all, color="primary")

            ui.separator()

            with ui.tabs().classes("w-full") as tabs:
                t_lcn = ui.tab("LCN")
                t_mqtt = ui.tab("MQTT")
                t_ha = ui.tab("Home Assistant")
                t_general = ui.tab("General")

            with ui.tab_panels(tabs, value=t_lcn).classes("w-full"):
                # ── LCN ──
                with ui.tab_panel(t_lcn):
                    d_lcn = cfg.get("lcn") or {}
                    with ui.column().classes("w-full gap-4 pt-4"):
                        lcn_host = ui.input(
                            "Host", value=d_lcn.get("host", "")
                        ).classes("w-full")
                        _env_mark(lcn_host, "lcn.host")
                        lcn_port = ui.number(
                            "Port",
                            value=d_lcn.get("port", 4114),
                            min=1,
                            max=65535,
                        ).classes("w-full")
                        _env_mark(lcn_port, "lcn.port")
                        lcn_username = ui.input(
                            "Username", value=d_lcn.get("username", "")
                        ).classes("w-full")
                        _env_mark(lcn_username, "lcn.username")
                        lcn_password = ui.input(
                            "Password",
                            value=d_lcn.get("password", ""),
                            password=True,
                            password_toggle_button=True,
                        ).classes("w-full")
                        _env_mark(lcn_password, "lcn.password")
                        dim_mode = ui.select(
                            ["STEPS50", "STEPS200"],
                            label="Dim mode",
                            value=(d_lcn.get("dim_mode") or "STEPS200").upper(),
                        ).classes("w-full")
                        _env_mark(dim_mode, "lcn.dim_mode")
                        sk_num_tries = ui.number(
                            "SK num tries",
                            value=d_lcn.get("sk_num_tries", 0),
                            min=0,
                        ).classes("w-full")
                        _env_mark(sk_num_tries, "lcn.sk_num_tries")
                        acknowledge = ui.switch(
                            "Acknowledge commands",
                            value=d_lcn.get("acknowledge_commands", False),
                        )
                        _env_mark(acknowledge, "lcn.acknowledge_commands")

                # ── MQTT ──
                with ui.tab_panel(t_mqtt):
                    d_mqtt = cfg.get("mqtt") or {}
                    with ui.column().classes("w-full gap-4 pt-4"):
                        base_topic = ui.input(
                            "Base topic",
                            value=d_mqtt.get("base_topic", "lcn2mqtt"),
                        ).classes("w-full")
                        _env_mark(base_topic, "mqtt.base_topic")
                        mqtt_host = ui.input(
                            "Host", value=d_mqtt.get("host", "")
                        ).classes("w-full")
                        _env_mark(mqtt_host, "mqtt.host")
                        mqtt_port = ui.number(
                            "Port",
                            value=d_mqtt.get("port", 1883),
                            min=1,
                            max=65535,
                        ).classes("w-full")
                        _env_mark(mqtt_port, "mqtt.port")
                        mqtt_username = ui.input(
                            "Username", value=d_mqtt.get("username") or ""
                        ).classes("w-full")
                        _env_mark(mqtt_username, "mqtt.username")
                        mqtt_password = ui.input(
                            "Password",
                            value=d_mqtt.get("password") or "",
                            password=True,
                            password_toggle_button=True,
                        ).classes("w-full")
                        _env_mark(mqtt_password, "mqtt.password")
                        qos = ui.select(
                            {
                                0: "0 \u2013 At most once",
                                1: "1 \u2013 At least once",
                                2: "2 \u2013 Exactly once",
                            },
                            label="QoS",
                            value=d_mqtt.get("qos", 0),
                        ).classes("w-full")
                        _env_mark(qos, "mqtt.qos")

                # ── Home Assistant ──
                with ui.tab_panel(t_ha):
                    d_ha = cfg.get("homeassistant") or {}
                    with ui.column().classes("w-full gap-4 pt-4"):
                        ha_enabled = ui.switch(
                            "Enable MQTT discovery",
                            value=d_ha.get("enabled", False),
                        )
                        _env_mark(ha_enabled, "homeassistant.enabled")
                        ha_prefix = ui.input(
                            "Discovery prefix",
                            value=d_ha.get("prefix", "homeassistant"),
                        ).classes("w-full")
                        _env_mark(ha_prefix, "homeassistant.prefix")
                        ha_scan_modules = ui.switch(
                            "Scan for modules on startup",
                            value=d_ha.get("scan_modules", True),
                        )
                        _env_mark(ha_scan_modules, "homeassistant.scan_modules")

                # ── General ──
                with ui.tab_panel(t_general), ui.column().classes("w-full gap-4 pt-4"):
                    log_level = ui.select(
                        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        label="Log level",
                        value=(cfg.get("log_level") or "INFO").upper(),
                    ).classes("w-full")
                    _env_mark(log_level, "log_level")
                    retained = ui.switch(
                        "Retain broker states on restart",
                        value=cfg.get("retained_broker_states", True),
                    )
                    _env_mark(retained, "retained_broker_states")
