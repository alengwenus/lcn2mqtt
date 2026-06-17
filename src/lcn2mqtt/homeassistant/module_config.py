"""Home Assistant MQTT Discovery configuration for LCN modules."""

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pypck.lcn_addr import LcnAddr

from .components import SwitchComponent


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

STANDARD_COMPONENTS = OUTPUTS | RELAYS


class HomeAssistantModuleDiscoveryConfig(BaseModel):
    """Home Assistant discovery configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="allow")

    address: LcnAddr = Field(..., exclude=True)

    include: set[str] = Field(default_factory=set)
    exclude: set[str] = Field(default_factory=set)

    switches: dict[str, SwitchComponent] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def setup_components(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Set up component models from the config."""
        for platform in ["switches"]:
            if platform not in data or not isinstance(data[platform], dict):
                data[platform] = {}

        # Setup include/exclude components
        take_cmps = set(data.get("include", STANDARD_COMPONENTS)) - set(
            data.get("exclude", set())
        )

        for cmp in take_cmps:
            if cmp in RELAYS:
                identifier = target = cmp
                data["switches"][identifier] = {
                    "target": target,
                }

        # Setup manually defined components
        for identifier, component in data.get("switches", {}).items():
            if isinstance(component, dict):
                component["address"] = data["address"]
                component["identifier"] = identifier

        return data

    def inject_basetopic(self, basetopic: str) -> None:
        """Inject the global basetopic into component models."""
        for component in self.switches.values():
            component.set_basetopic(basetopic)
