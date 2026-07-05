"""Home Assistant MQTT Discovery configuration for LCN modules."""

import fnmatch
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from pypck import lcn_defs
from pypck.lcn_addr import LcnAddr

from .components import (
    BinarySensorComponent,
    ClimateComponent,
    CoverComponent,
    LightComponent,
    NumberComponent,
    SelectComponent,
    SensorComponent,
    SwitchComponent,
)

BINSENSORS = tuple(key.lower() for key in lcn_defs.BinSensorPort.__members__)
OUTPUTS = tuple(key.lower() for key in lcn_defs.OutputPort.__members__)
RELAYS = tuple(key.lower() for key in lcn_defs.RelayPort.__members__)
MOTORS = tuple(key.lower() for key in lcn_defs.MotorPort.__members__)
LEDS = tuple(key.lower() for key in lcn_defs.LedPort.__members__)
VARS = tuple(key.lower() for key in lcn_defs.Var.__members__)

STANDARD_COMPONENTS = (
    lcn_defs.OutputPort.OUTPUT1.name.lower(),
    lcn_defs.OutputPort.OUTPUT2.name.lower(),
    *(key.lower() for key in lcn_defs.RelayPort.__members__ if key.startswith("RELAY")),
)

ALL_COMPONENTS = BINSENSORS + OUTPUTS + RELAYS + MOTORS + LEDS + VARS

PLATFORMS = (
    "binary_sensors",
    "switches",
    "lights",
    "sensors",
    "numbers",
    "selects",
    "covers",
    "climates",
)


class HomeAssistantModuleDiscoveryConfig(BaseModel):
    """Home Assistant discovery configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="forbid")

    address: LcnAddr | None = Field(default=None, exclude=True)

    include: set[str] = set(STANDARD_COMPONENTS)
    exclude: set[str] = Field(default_factory=set)

    binary_sensors: dict[str, BinarySensorComponent] = Field(default_factory=dict)
    switches: dict[str, SwitchComponent] = Field(default_factory=dict)
    lights: dict[str, LightComponent] = Field(default_factory=dict)
    sensors: dict[str, SensorComponent] = Field(default_factory=dict)
    numbers: dict[str, NumberComponent] = Field(default_factory=dict)
    selects: dict[str, SelectComponent] = Field(default_factory=dict)
    covers: dict[str, CoverComponent] = Field(default_factory=dict)
    climates: dict[str, ClimateComponent] = Field(default_factory=dict)

    @property
    def components(self) -> dict[str, Any]:
        """Return a dict of all components by platform."""
        return {
            **self.binary_sensors,
            **self.switches,
            **self.lights,
            **self.sensors,
            **self.numbers,
            **self.selects,
            **self.covers,
            **self.climates,
        }

    def prepare_auto_components(self) -> None:
        """Update the automatically included components based on include/exclude."""
        include = {
            cmp.lower()
            for include_cmp in self.include
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp.lower(), include_cmp)
        }
        exclude = {
            cmp.lower()
            for exclude_cmp in self.exclude or set()
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp.lower(), exclude_cmp)
        }
        take_cmps = include - exclude

        # Automatically set up include/exclude components
        for cmp in take_cmps:
            if cmp in RELAYS:
                identifier = target = cmp
                self.switches.setdefault(identifier, SwitchComponent(target=target))
            elif cmp in OUTPUTS:
                identifier = target = cmp
                self.lights.setdefault(identifier, LightComponent(target=target))
            elif cmp in BINSENSORS:
                identifier = source = cmp
                self.binary_sensors.setdefault(
                    identifier, BinarySensorComponent(source=source)
                )
            elif cmp in VARS:
                identifier = target = cmp
                self.numbers.setdefault(identifier, NumberComponent(target=target))
            elif cmp in LEDS:
                identifier = target = cmp
                self.selects.setdefault(identifier, SelectComponent(target=target))
            elif cmp in MOTORS:
                identifier = target = cmp
                self.covers.setdefault(identifier, CoverComponent(target=target))

    def update_components(self) -> None:
        """Update the components with the current address and identifier."""
        for identifier, component in self.components.items():
            component.update_properties(self.address, identifier)

    def update_base_topic(self, base_topic: str) -> None:
        """Set the base topic for all components."""
        for component in self.components.values():
            component.update_base_topic(base_topic)
