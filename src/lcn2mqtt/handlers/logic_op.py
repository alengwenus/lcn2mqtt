"""Handler for LCN logic operation status outputs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pypck import inputs, lcn_defs

from lcn2mqtt.handlers.dispatcher import input_handler, mqtt_handler
from lcn2mqtt.helpers import MqttMessage

from ..models.device import Device, LogicOpState

_LOG = logging.getLogger(__name__)


if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge


@input_handler(inputs.ModStatusLedsAndLogicOps)
def handle_input(
    inp: inputs.ModStatusLedsAndLogicOps, module: Device, bridge: Bridge
) -> None:
    """Handle a logic operation status input, update the module state, and publish any changes."""
    states = [LogicOpState(state.name.lower()) for state in inp.states_logic_ops]
    changed = module.update_logic_ops(states)
    for idx, did_change in enumerate(changed, start=1):
        if did_change:
            bridge.publish(
                module.prefix,
                MqttMessage(f"logic_op/{idx}/state", states[idx - 1].value),
            )


@mqtt_handler("logic_op/+/state")
async def handle_retained_state(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a request for the retained state of a logic operation."""
    if not bridge.config.retained_broker_states:
        return
    parts = subtopic.split("/")
    try:
        idx = int(parts[1])
    except ValueError:
        return
    if not 1 <= idx <= 4:
        return

    try:
        setattr(module, f"logic_op{idx}", LogicOpState(payload.lower()))
    except ValueError:
        _LOG.warning("Invalid logic operation state payload %r", payload)
        return


@mqtt_handler("logic_op/+/get", "logic_op/get")
async def handle_get_command(
    subtopic: str, payload: str, module: Device, bridge: Bridge
) -> None:
    """Handle a command to get the current state of a logic operation."""
    device_connection = module.device_connection
    parts = subtopic.split("/")
    try:
        if parts[1] == "get":
            logic_ops = [lcn_defs.LogicOpPort(i) for i in range(4)]
        else:
            idx = int(parts[1])
            logic_ops = [lcn_defs.LogicOpPort(idx - 1)]
    except ValueError:
        return

    result_input = await device_connection.request_status_leds_and_logic_ops()
    if result_input is None:
        return

    # Publish the current state of the requested logic operation
    for logic_op in logic_ops:
        logic_op_state = result_input.states_logic_ops[logic_op.value]
        bridge.publish(
            module.prefix,
            MqttMessage(
                f"logic_op/{logic_op.value + 1}/state", logic_op_state.name.lower()
            ),
        )
