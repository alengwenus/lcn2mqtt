"""Home Assistant MQTT Discovery configuration for LCN modules."""

import fnmatch
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
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

BINSENSORS = tuple(key.lower() for key in lcn_defs.BinSensorPort.__members__.keys())
OUTPUTS = tuple(key.lower() for key in lcn_defs.OutputPort.__members__.keys())
RELAYS = tuple(key.lower() for key in lcn_defs.RelayPort.__members__.keys())
MOTORS = tuple(key.lower() for key in lcn_defs.MotorPort.__members__.keys())
LEDS = tuple(key.lower() for key in lcn_defs.LedPort.__members__.keys())
VARS = tuple(key.lower() for key in lcn_defs.Var.__members__.keys())

STANDARD_COMPONENTS = (
    lcn_defs.OutputPort.OUTPUT1.name.lower(),
    lcn_defs.OutputPort.OUTPUT2.name.lower(),
    *(
        key.lower()
        for key in lcn_defs.RelayPort.__members__.keys()
        if key.startswith("RELAY")
    ),
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

    address: LcnAddr = Field(..., exclude=True)

    include: set[str] = Field(default_factory=set)
    exclude: set[str] = Field(default_factory=set)

    binary_sensors: dict[str, BinarySensorComponent] = Field(default_factory=dict)
    switches: dict[str, SwitchComponent] = Field(default_factory=dict)
    lights: dict[str, LightComponent] = Field(default_factory=dict)
    sensors: dict[str, SensorComponent] = Field(default_factory=dict)
    numbers: dict[str, NumberComponent] = Field(default_factory=dict)
    selects: dict[str, SelectComponent] = Field(default_factory=dict)
    covers: dict[str, CoverComponent] = Field(default_factory=dict)
    climates: dict[str, ClimateComponent] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def setup_components(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Set up component models from the config."""
        for platform in PLATFORMS:
            if platform not in data or not isinstance(data[platform], dict):
                data[platform] = {}

        # Process wildcard entries in include/exclude
        include = {
            cmp.lower()
            for include_cmp in data.get("include", STANDARD_COMPONENTS)
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp.lower(), include_cmp)
        }
        exclude = {
            cmp.lower()
            for exclude_cmp in data.get("exclude", set())
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp.lower(), exclude_cmp)
        }
        take_cmps = include - exclude

        # Automatically set up include/exclude components
        for cmp in take_cmps:
            if cmp in RELAYS:
                identifier = target = cmp
                data["switches"][identifier] = {
                    "target": target,
                }
            elif cmp in OUTPUTS:
                identifier = target = cmp
                data["lights"][identifier] = {
                    "target": target,
                }
            elif cmp in BINSENSORS:
                identifier = source = cmp
                data["binary_sensors"][identifier] = {
                    "source": source,
                }
            elif cmp in VARS:
                identifier = target = cmp
                data["numbers"][identifier] = {
                    "target": target,
                }
            elif cmp in LEDS:
                identifier = target = cmp
                data["selects"][identifier] = {
                    "target": target,
                }
            elif cmp in MOTORS:
                identifier = target = cmp
                data["covers"][identifier] = {
                    "target": target,
                }

        # Set properties of manual and automatically defined components
        for platform in PLATFORMS:
            for identifier, component in data.get(platform, {}).items():
                if isinstance(component, dict):
                    component["address"] = data["address"]
                    component["identifier"] = identifier

        return data

    def inject_basetopic(self, basetopic: str) -> None:
        """Inject the global basetopic into component models."""
        for platform in PLATFORMS:
            for component in getattr(self, platform).values():
                component.set_basetopic(basetopic)

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
