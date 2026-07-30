"""Handler for LCN output ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Generator
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device, Output, OutputState

_LOG = logging.getLogger(__name__)

Publish = Callable[[str, Any], Awaitable[None]]

_DEFAULT_TRANSITION_MS = 500


if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusOutput)
def handle_input(inp: inputs.ModStatusOutput, module: Device) -> Generator[MqttMessage]:
    """Handle an output status input, update the module state, and publish any changes."""
    idx = inp.output_id + 1  # 0-based -> 1-based
    output = getattr(module, f"output{idx}")

    state_changed = output.update_state(
        OutputState.ON if inp.percent > 0 else OutputState.OFF
    )
    # brightness_changed = output.update_brightness(inp.percent)
    brightness_changed = True  # Always publish brightness, even if unchanged, to ensure retained state is correct

    if state_changed:
        yield MqttMessage(
            f"output/{idx}/state",
            output.state.value if output.state is not None else None,
        )
    if brightness_changed:
        yield MqttMessage(f"output/{idx}/brightness", f"{inp.percent:.2f}")


@mqtt_handler("output/+/set_brightness")
async def handle_set_brightness(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change an output state or brightness."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    output: Output = getattr(module, f"output{idx}")

    try:
        brightness = float(payload)
        output.brightness = brightness
    except (ValueError, ValidationError):
        _LOG.warning("Invalid brightness payload %r", payload)
        return


@mqtt_handler("output/+/set_transition")
async def handle_set_transition(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change an output state or brightness."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    output: Output = getattr(module, f"output{idx}")

    try:
        transition = int(payload)
        output.transition = transition
    except (ValueError, ValidationError):
        _LOG.warning("Invalid transition payload %r", payload)
        return


@mqtt_handler("output/+/set")
async def handle_set(
    subtopic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
) -> None:
    """Handle a command to change an output state or brightness."""
    device_connection = module.device_connection
    if device_connection is None:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    output: Output = getattr(module, f"output{idx}")

    transition_ms = (
        output.transition if output.transition is not None else _DEFAULT_TRANSITION_MS
    )
    ramp = lcn_defs.time_to_ramp_value(transition_ms)

    if payload == "on":
        if output.state == OutputState.OFF:
            await device_connection.toggle_output(idx - 1, ramp, to_memory=True)
            return
        brightness = output.brightness if output.brightness is not None else 100.0
    elif payload == "off":
        if output.state == OutputState.ON:
            await device_connection.toggle_output(idx - 1, ramp, to_memory=True)
            return
        brightness = 0.0
    else:  # payload is a brightness value
        try:
            brightness = float(payload)
        except ValueError:
            _LOG.warning("Invalid output payload %r", payload)
            return
    brightness = max(0.0, min(100.0, brightness))

    await device_connection.dim_output(idx - 1, brightness, ramp)


@mqtt_handler("output/+/state", "output/+/brightness")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a relay."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
        action = parts[2]
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    output = getattr(module, f"output{idx}")
    if action == "state":
        try:
            output.state = OutputState(payload.lower())
        except ValueError:
            _LOG.warning("Invalid output state payload %r", payload)
            return
    elif action == "brightness":
        try:
            output.brightness = float(payload)
        except (ValueError, ValidationError):
            _LOG.warning("Invalid output brightness payload %r", payload)
            return
