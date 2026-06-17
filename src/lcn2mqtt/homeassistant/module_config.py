"""Home Assistant MQTT Discovery configuration for LCN modules."""

import fnmatch
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pypck.lcn_addr import LcnAddr

from .components import (
    SwitchComponent,
    LightComponent,
    SensorComponent,
    NumberComponent,
    SelectComponent,
)

OUTPUTS = {"output1", "output2", "output3", "output4"}
RELAYS = {
    "relay1",
    "relay2",
    "relay3",
    "relay4",
    "relay5",
    "relay6",
    "relay7",
    "relay8",
}
MOTORS = {"motor1", "motor2", "motor3", "motor4"}
LEDS = {
    "led1",
    "led2",
    "led3",
    "led4",
    "led5",
    "led6",
    "led7",
    "led8",
    "led9",
    "led10",
    "led11",
    "led12",
}
VARS = {
    "var1",
    "var2",
    "var3",
    "var4",
    "var5",
    "var6",
    "var7",
    "var8",
    "var9",
    "var10",
    "var11",
    "var12",
}
VARS_OLD = {
    "tvar",
    "r1var",
    "r2var",
}
SETPOINTS = {
    "setpoint1",
    "setpoint2",
}
THRESHOLDS = {
    "thrs1",
    "thrs2",
    "thrs3",
    "thrs4",
    "thrs2_1",
    "thrs2_2",
    "thrs2_3",
    "thrs2_4",
    "thrs3_1",
    "thrs3_2",
    "thrs3_3",
    "thrs3_4",
    "thrs4_1",
    "thrs4_2",
    "thrs4_3",
    "thrs4_4",
}
THRESHOLDS_OLD = {
    "thrs1",
    "thrs2",
    "thrs3",
    "thrs4",
    "thrs5",
}


STANDARD_COMPONENTS = OUTPUTS | RELAYS

ALL_COMPONENTS = (
    OUTPUTS
    | RELAYS
    | MOTORS
    | LEDS
    | VARS
    | VARS_OLD
    | SETPOINTS
    | THRESHOLDS
    | THRESHOLDS_OLD
)

PLATFORMS = ("switches", "lights", "sensors", "numbers", "selects")


class HomeAssistantModuleDiscoveryConfig(BaseModel):
    """Home Assistant discovery configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="allow")

    address: LcnAddr = Field(..., exclude=True)

    include: set[str] = Field(default_factory=set)
    exclude: set[str] = Field(default_factory=set)

    switches: dict[str, SwitchComponent] = Field(default_factory=dict)
    lights: dict[str, LightComponent] = Field(default_factory=dict)
    sensors: dict[str, SensorComponent] = Field(default_factory=dict)
    numbers: dict[str, NumberComponent] = Field(default_factory=dict)
    selects: dict[str, SelectComponent] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def setup_components(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Set up component models from the config."""
        for platform in PLATFORMS:
            if platform not in data or not isinstance(data[platform], dict):
                data[platform] = {}

        # Process wildcard entries in include/exclude
        include = {
            cmp
            for include_cmp in data.get("include", STANDARD_COMPONENTS)
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp, include_cmp)
        }
        exclude = {
            cmp
            for exclude_cmp in data.get("exclude", set())
            for cmp in ALL_COMPONENTS
            if fnmatch.fnmatch(cmp, exclude_cmp)
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
            elif cmp in VARS | VARS_OLD | SETPOINTS | THRESHOLDS | THRESHOLDS_OLD:
                identifier = target = cmp
                data["numbers"][identifier] = {
                    "target": target,
                }
            elif cmp in LEDS:
                identifier = target = cmp
                data["selects"][identifier] = {
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
