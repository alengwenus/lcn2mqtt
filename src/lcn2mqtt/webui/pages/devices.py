"""Devices configuration page (/devices)."""

from __future__ import annotations

from typing import Any

from nicegui import ui
from pypck import lcn_defs

from ..app import page_frame
from ..config_io import read_yaml, write_yaml
from ..helpers import device_title
from ..manager import BridgeManager

_VAR_UNIT_OPTS: dict[str, str] = {
    n.lower(): n.lower() for n in lcn_defs.VarUnit.__members__
}
_MOT_POS_OPTS: dict[str, str] = {
    n.lower(): n.lower() for n in lcn_defs.MotorPositioningMode.__members__
}
# motor_outputs only supports NONE and MODULE positioning modes
_MOT_POS_OUTPUTS_OPTS: dict[str, str] = {
    k: v for k, v in _MOT_POS_OPTS.items() if k in ("none", "module")
}
_RT_OPTS: dict[str, str] = {
    n.lower(): n.lower() for n in lcn_defs.MotorReverseTime.__members__
}

_VAR_NAMES = [*(f"variable{i}" for i in range(1, 13)), "setpoint1", "setpoint2"]
_OUTPUT_NAMES = [f"output{i}" for i in range(1, 5)]
_MOTOR_NAMES = [f"motor{i}" for i in range(1, 5)]


def register(manager: BridgeManager) -> None:
    """Register the /devices page with NiceGUI."""

    @ui.page("/devices")
    def devices_page() -> None:
        banner = page_frame(manager)

        save_fns: list[Any] = []

        @ui.refreshable
        def device_list() -> None:
            save_fns.clear()
            cfg = read_yaml()
            devices: dict[str, Any] = cfg.get("devices") or {}

            if not devices:
                ui.label("No devices configured yet.").classes("text-grey-6 italic")
                return

            for addr_str, device_data in devices.items():
                _device_card(
                    manager, addr_str, device_data or {}, device_list, save_fns
                )

        async def save_all() -> None:
            for fn in save_fns:
                await fn()
            manager.restart_needed = True
            banner.refresh()

        async def scan() -> None:
            try:
                found = await manager.scan_modules()
            except RuntimeError as exc:
                ui.notify(str(exc), type="negative")
                return
            cfg = read_yaml()
            devs: dict[str, Any] = cfg.get("devices") or {}
            new_addrs = [a for a in found if a not in devs]
            if not new_addrs:
                ui.notify("No new modules found", type="info")
                return
            for addr_str in new_addrs:
                devs[addr_str] = {}
            cfg["devices"] = devs
            write_yaml(cfg)
            device_list.refresh()
            ui.notify(f"Added {len(new_addrs)} new module(s)", type="positive")

        with ui.column().classes("w-full p-4 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Devices").classes("text-h5")
                with ui.row().classes("gap-2"):
                    ui.button("Scan", icon="radar", on_click=scan, color="secondary")
                    ui.button(
                        "Save All", icon="save", on_click=save_all, color="primary"
                    )

            # ── Add device ──
            with ui.card().classes("w-full max-w-2xl"):
                with ui.card_section():
                    ui.label("Add Device").classes("text-subtitle1 font-medium")
                with ui.card_section():  # noqa: SIM117
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        addr_type = ui.select(
                            {"m": "Module (m)", "g": "Group (g)"},
                            value="m",
                            label="Type",
                        ).classes("w-32")
                        seg_in = ui.number("Segment", value=0, min=0, max=9).classes(
                            "w-28"
                        )
                        addr_in = ui.number("Address", value=1, min=1, max=127).classes(
                            "w-28"
                        )

                        def add_device() -> None:
                            addr_str = (
                                f"{addr_type.value}"
                                f"{int(seg_in.value or 0):03d}"
                                f"{int(addr_in.value or 1):03d}"
                            )
                            cfg = read_yaml()
                            devs: dict[str, Any] = cfg.get("devices") or {}
                            if addr_str in devs:
                                ui.notify(f"{addr_str} already exists", type="warning")
                                return
                            devs[addr_str] = {}
                            cfg["devices"] = devs
                            write_yaml(cfg)
                            device_list.refresh()
                            ui.notify(f"Added {addr_str}", type="positive")

                        ui.button(
                            "Add", icon="add", on_click=add_device, color="primary"
                        )

            device_list()


def _device_card(
    manager: BridgeManager,
    addr_str: str,
    device_data: dict[str, Any],
    refresh_fn: Any,
    save_fns: list[Any],
) -> None:
    """Render one expandable device card."""
    with ui.expansion(
        device_title(manager, addr_str, device_data), icon="device_hub"
    ).classes("w-full max-w-4xl border border-grey-3 rounded"):
        # Delete button row
        with ui.row().classes("justify-end w-full pb-1"):

            def _delete(a: str = addr_str) -> None:
                cfg = read_yaml()
                devs: dict[str, Any] = cfg.get("devices") or {}
                devs.pop(a, None)
                cfg["devices"] = devs
                write_yaml(cfg)
                refresh_fn.refresh()
                ui.notify(f"Deleted {a}", type="positive")

            ui.button(icon="delete", on_click=_delete).props(
                "flat dense color=negative"
            ).tooltip("Delete device")

        # ── Tabs ──
        with ui.tabs().classes("w-full") as tabs:
            t_out = ui.tab("Outputs")
            t_var = ui.tab("Variables")
            t_mot = ui.tab("Motors")

        out_inputs: dict[str, ui.number] = {}
        var_selects: dict[str, ui.select] = {}
        mot_selects: dict[str, ui.select] = {}

        with ui.tab_panels(tabs, value=t_out).classes("w-full border-t"):
            # ── Outputs ──
            with ui.tab_panel(t_out):  # noqa: SIM117
                with ui.grid(columns=2).classes("w-full gap-4 p-4"):
                    for i in range(1, 5):
                        key = f"output{i}"
                        ov = device_data.get(key) or {}
                        out_inputs[key] = ui.number(
                            f"Output {i} transition (ms)",
                            value=ov.get("transition"),
                            min=0,
                        ).classes("w-full")

            # ── Variables ──
            with ui.tab_panel(t_var):  # noqa: SIM117
                with ui.grid(columns=2).classes("w-full gap-4 p-4"):
                    for name in _VAR_NAMES:
                        vdata = device_data.get(name) or {}
                        unit = (vdata.get("unit") or "native").lower()
                        var_selects[name] = ui.select(
                            _VAR_UNIT_OPTS, label=f"{name} unit", value=unit
                        ).classes("w-full")

            # ── Motors ──
            with ui.tab_panel(t_mot):
                with ui.grid(columns=2).classes("w-full gap-4 p-4"):
                    for i in range(1, 5):
                        key = f"motor{i}"
                        mdata = device_data.get(key) or {}
                        pm = (mdata.get("positioning_mode") or "none").lower()
                        mot_selects[key] = ui.select(
                            _MOT_POS_OPTS,
                            label=f"Motor {i} positioning mode",
                            value=pm,
                        ).classes("w-full")

                ui.separator().classes("my-2")
                ui.label("Motor Outputs").classes("text-subtitle2 px-4 pt-1")
                mo_data = device_data.get("motor_outputs") or {}
                with ui.column().classes("px-4 gap-3 pb-4"):
                    motor_rt = ui.select(
                        _RT_OPTS,
                        label="Reverse time",
                        value=(mo_data.get("reverse_time") or "rt70").lower(),
                    ).classes("w-full")
                    motor_pm = ui.select(
                        _MOT_POS_OUTPUTS_OPTS,
                        label="Positioning mode",
                        value=(mo_data.get("positioning_mode") or "none").lower(),
                    ).classes("w-full")
                    motor_timeout = ui.number(
                        "Stop timeout (s)", value=mo_data.get("stop_timeout")
                    ).classes("w-full")

        # ── Save button ──
        async def _save(a: str = addr_str) -> None:
            dev: dict[str, Any] = {}

            for k, inp in out_inputs.items():
                if inp.value is not None and str(inp.value).strip():
                    dev[k] = {"transition": int(inp.value)}

            for k, sel in var_selects.items():
                if sel.value and sel.value != "native":
                    dev[k] = {"unit": sel.value}

            for k, sel in mot_selects.items():
                if sel.value and sel.value != "none":
                    dev[k] = {"positioning_mode": sel.value}

            mo: dict[str, Any] = {}
            if motor_rt.value != "rt70":
                mo["reverse_time"] = motor_rt.value
            if motor_pm.value != "none":
                mo["positioning_mode"] = motor_pm.value
            if motor_timeout.value is not None and str(motor_timeout.value).strip():
                mo["stop_timeout"] = float(motor_timeout.value)
            if mo:
                dev["motor_outputs"] = mo

            cfg = read_yaml()
            devs: dict[str, Any] = cfg.get("devices") or {}
            # preserve HA config — managed on the Home Assistant page
            existing_ha = (devs.get(a) or {}).get("homeassistant")
            if existing_ha:
                dev["homeassistant"] = existing_ha
            devs[a] = dev
            cfg["devices"] = devs
            write_yaml(cfg)
            ui.notify(f"Device {a} saved", type="positive")

        save_fns.append(_save)
