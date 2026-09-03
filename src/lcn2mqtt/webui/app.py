"""NiceGUI application shell: header, navigation drawer, and restart banner."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from .manager import BridgeManager

# from .pages import general

_CONFIG = [
    ("General", "/general"),
    ("Devices", "/devices"),
    ("Discovery", "/discovery"),
]

_MONITOR = [
    ("Modules", "/modules"),
]


def page_frame(manager: BridgeManager) -> Any:
    """Render the common header and left drawer. Returns the banner refreshable."""

    @ui.refreshable
    def status_chip() -> None:
        if manager.is_running:
            ui.chip("Running", icon="check_circle", color="positive").props("outline")
        else:
            ui.chip("Stopped", icon="stop_circle", color="negative").props("outline")

    @ui.refreshable
    def banner() -> None:
        if manager.restart_needed:
            with ui.row().classes(
                "w-full bg-amber-100 border border-amber-400 rounded-lg "
                "p-3 items-center gap-3"
            ):
                ui.icon("warning", color="orange")
                ui.label("Bridge restart required to apply changes").classes(
                    "flex-1 text-amber-900"
                )
                ui.button("Restart Now", on_click=_restart).props(
                    "color=warning outline"
                )

    async def _restart() -> None:
        try:
            await manager.restart()
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return
        manager.restart_needed = False
        banner.refresh()
        status_chip.refresh()
        ui.notify("Bridge restarted", type="positive")

    # Drawer must be defined before the header so the menu-button lambda can reference it.
    with ui.left_drawer(top_corner=True).classes(
        "bg-indigo-50 border-r border-indigo-200 p-2"
    ) as drawer:
        ui.label("Configuration").classes("text-overline text-grey-7 px-2 pt-2 pb-1")
        for label, path in _CONFIG:
            ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).classes(
                "w-full justify-start"
            ).props("flat no-caps align=left")

        ui.label("Monitor").classes("text-overline text-grey-7 px-2 pt-2 pb-1")
        for label, path in _MONITOR:
            ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).classes(
                "w-full justify-start"
            ).props("flat no-caps align=left")

    with ui.header().classes("items-center gap-2 px-4 bg-indigo-800"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat color=white dense")
        ui.label("lcn2mqtt").classes("text-h6 text-white ml-1")
        ui.space()
        status_chip()
        ui.timer(5.0, status_chip.refresh)
        ui.button("Restart Bridge", icon="refresh", on_click=_restart).props(
            "flat color=white"
        )

    banner()
    return banner


def setup_ui(manager: BridgeManager) -> None:
    """Register all WebUI pages with NiceGUI."""
    from .pages import devices, discovery, general, modules  # noqa: PLC0415

    general.register(manager)
    devices.register(manager)
    discovery.register(manager)
    modules.register(manager)

    @ui.page("/")
    def root() -> None:
        ui.navigate.to("/general")
