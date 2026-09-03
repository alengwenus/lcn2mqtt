"""Live module state page (/modules)."""

from __future__ import annotations

from nicegui import ui

from lcn2mqtt.models.config import DeviceConfig
from lcn2mqtt.models.device import Variable

from ..app import page_frame
from ..manager import BridgeManager

_CHIP_COLORS = {
    "on": "positive",
    "open": "positive",
    "off": "grey-6",
    "closed": "grey-6",
    "blink": "warning",
    "flicker": "warning",
    "opening": "warning",
    "closing": "warning",
    "none": "grey-6",
    "some": "warning",
    "all": "positive",
}


def register(manager: BridgeManager) -> None:
    """Register the /modules page with NiceGUI."""
    open_states: dict[str, bool] = {}

    @ui.page("/modules")
    def modules_page() -> None:
        page_frame(manager)

        @ui.refreshable
        def module_list() -> None:
            if not manager.is_running:
                ui.label(
                    "Bridge is not running. Start it to see module states."
                ).classes("text-grey-6 italic")
                return

            devices = manager.devices
            if not devices:
                ui.label("No modules known yet.").classes("text-grey-6 italic")
                return

            for device in devices.values():
                _module_card(device, open_states)

        async def refresh_from_bus() -> None:
            try:
                await manager.poll_bus_status()
            except RuntimeError as exc:
                ui.notify(str(exc), type="negative")
                return
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"Bus refresh failed: {exc}", type="negative")
                return
            ui.notify("Requested status from all modules", type="positive")
            module_list.refresh()

        with ui.column().classes("w-full p-4 gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Module States").classes("text-h5")
                ui.button(
                    "Refresh from bus",
                    icon="sync",
                    on_click=refresh_from_bus,
                    color="primary",
                )
            module_list()
            ui.timer(2.0, module_list.refresh)


def _state_chip(label: str, value: str | None) -> None:
    """Render a colored state chip; grey dash for unknown values."""
    if value is None:
        ui.chip(f"{label}: —", color="grey-3").props("outline dense")
    else:
        color = _CHIP_COLORS.get(value, "primary")
        ui.chip(f"{label}: {value}", color=color).props("outline dense")


def _module_card(device: DeviceConfig, open_states: dict[str, bool]) -> None:
    """Render one module's state card, preserving the expansion open state."""
    key = device.address.to_string()
    addr = key.upper()
    title = f"{device.name} ({addr})" if device.name else addr
    expansion = ui.expansion(
        title,
        icon="memory",
        value=open_states.get(key, False),
        on_value_change=lambda e, k=key: open_states.__setitem__(k, e.value),
    ).classes("w-full max-w-5xl border border-grey-3 rounded")
    with expansion, ui.column().classes("w-full p-4 gap-4"):
        _identity_section(device)
        if device.address.is_group:
            ui.label("Groups do not support status requests.").classes(
                "text-grey-6 italic"
            )
            return
        _outputs_section(device)
        _relays_section(device)
        _leds_logic_section(device)
        _binsensors_section(device)
        _variables_section(device)
        _motors_section(device)


def _section_label(text: str) -> None:
    ui.label(text).classes("text-subtitle2")


def _identity_section(device: DeviceConfig) -> None:
    serials = device.serials
    with ui.column().classes("gap-1"):
        _section_label("Identity")
        with ui.row().classes("gap-4 text-body2 text-grey-8"):
            ui.label(f"Address: {device.address.to_string().upper()}")
            ui.label(f"Prefix: {device.prefix}")
            if serials.hardware != -1:
                ui.label(f"HW: {serials.hardware:#010x}")
            if serials.software != -1:
                ui.label(f"SW: {serials.software:#08x}")
            if serials.type.value >= 0:
                ui.label(f"Type: {serials.type.name}")


def _outputs_section(device: DeviceConfig) -> None:
    outputs = [getattr(device, f"output{i}") for i in range(1, 5)]
    if all(o.state is None and o.brightness is None for o in outputs):
        return
    with ui.column().classes("gap-1"):
        _section_label("Outputs")
        with ui.row().classes("gap-2 flex-wrap"):
            for i, output in enumerate(outputs, start=1):
                label = f"Out {i}"
                if output.brightness is not None:
                    label += f" ({output.brightness:.0f}%)"
                _state_chip(label, output.state.value if output.state else None)


def _relays_section(device: DeviceConfig) -> None:
    relays = [getattr(device, f"relay{i}") for i in range(1, 9)]
    if all(r is None for r in relays):
        return
    with ui.column().classes("gap-1"):
        _section_label("Relays")
        with ui.row().classes("gap-2 flex-wrap"):
            for i, relay in enumerate(relays, start=1):
                _state_chip(f"R{i}", relay.value if relay else None)


def _leds_logic_section(device: DeviceConfig) -> None:
    leds = [getattr(device, f"led{i}") for i in range(1, 13)]
    logic_ops = [getattr(device, f"logic_op{i}") for i in range(1, 5)]
    if all(v is None for v in leds) and all(v is None for v in logic_ops):
        return
    with ui.column().classes("gap-1"):
        _section_label("LEDs & Logic Ops")
        if any(v is not None for v in leds):
            with ui.row().classes("gap-2 flex-wrap"):
                for i, led in enumerate(leds, start=1):
                    _state_chip(f"LED{i}", led.value if led else None)
        if any(v is not None for v in logic_ops):
            with ui.row().classes("gap-2 flex-wrap"):
                for i, op in enumerate(logic_ops, start=1):
                    _state_chip(f"LO{i}", op.value if op else None)


def _binsensors_section(device: DeviceConfig) -> None:
    binsensors = [getattr(device, f"binsensor{i}") for i in range(1, 9)]
    if all(b is None for b in binsensors):
        return
    with ui.column().classes("gap-1"):
        _section_label("Binary Sensors")
        with ui.row().classes("gap-2 flex-wrap"):
            for i, sensor in enumerate(binsensors, start=1):
                _state_chip(
                    f"B{i}", None if sensor is None else ("on" if sensor else "off")
                )


def _variable_chip(label: str, variable: Variable) -> None:
    """Render a variable chip with value, unit, and lock indicator."""
    if variable.value is None:
        ui.chip(f"{label}: —", color="grey-3").props("outline dense")
        return
    text = f"{label}: {variable.value}"
    if variable.unit.value != "native":
        text += f" {variable.unit.value}"
    if variable.locked:
        text += " 🔒"
    ui.chip(text, color="primary").props("outline dense")


def _variables_section(device: DeviceConfig) -> None:
    variables = [getattr(device, f"variable{i}") for i in range(1, 13)]
    setpoints = [device.setpoint1, device.setpoint2]
    thresholds = [
        getattr(device, f"threshold{reg}{idx}")
        for reg in range(1, 5)
        for idx in range(1, 5)
    ]
    var_names = ["T", "R1", "R2"] + [f"V{i}" for i in range(4, 13)]

    if (
        all(v.value is None for v in variables)
        and all(v.value is None for v in setpoints)
        and all(v.value is None for v in thresholds)
    ):
        return

    with ui.column().classes("gap-1"):
        _section_label("Variables")
        if any(v.value is not None for v in variables):
            with ui.row().classes("gap-2 flex-wrap"):
                for name, var in zip(var_names, variables, strict=True):
                    _variable_chip(name, var)
        if any(v.value is not None for v in setpoints):
            with ui.row().classes("gap-2 flex-wrap"):
                for i, sp in enumerate(setpoints, start=1):
                    _variable_chip(f"S{i}", sp)
        if any(v.value is not None for v in thresholds):
            with ui.row().classes("gap-2 flex-wrap"):
                for reg in range(1, 5):
                    for idx in range(1, 5):
                        _variable_chip(
                            f"Th{reg}.{idx}",
                            getattr(device, f"threshold{reg}{idx}"),
                        )


def _motors_section(device: DeviceConfig) -> None:
    motors = [getattr(device, f"motor{i}") for i in range(1, 5)]
    motor_outputs = device.motor_outputs
    if all(m.state is None and m.position is None for m in motors) and (
        motor_outputs.state is None
    ):
        return
    with ui.column().classes("gap-1"):
        _section_label("Motors")
        if any(m.state is not None or m.position is not None for m in motors):
            with ui.row().classes("gap-2 flex-wrap"):
                for i, motor in enumerate(motors, start=1):
                    label = f"M{i}"
                    if motor.position is not None:
                        label += f" ({motor.position:.0f}%)"
                    _state_chip(label, motor.state.value if motor.state else None)
        if motor_outputs.state is not None:
            with ui.row().classes("gap-2 flex-wrap"):
                _state_chip("Outputs", motor_outputs.state.value)
