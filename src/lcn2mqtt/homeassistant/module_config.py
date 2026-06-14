"""Home Assistant MQTT Discovery configuration for LCN modules."""

import json
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pypck.lcn_addr import LcnAddr

from .components import SwitchComponent


class HomeAssistantModuleDiscoveryConfig(BaseModel):
    """Home Assistant discovery configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="allow")

    address: LcnAddr = Field(..., exclude=True)

    include: dict[str, list[int]] = {}
    exclude: dict[str, list[int]] = {}

    switches: dict[str, SwitchComponent] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def setup_components(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Set up component models from the config."""
        for identifier, component in data.get("switches", {}).items():
            if isinstance(component, dict):
                component["address"] = data["address"]
                component["identifier"] = identifier

        return data

    @field_validator("include", "exclude", mode="before")
    @classmethod
    def parse_list(cls, value: dict[str, list[int]]) -> dict[str, list[int]]:
        """Parse comma-separated strings into lists of ints."""
        result: dict[str, list[int]] = {}
        for key, val in value.items():
            if isinstance(val, str):
                result[key] = json.loads(val.strip("'"))
            elif isinstance(val, list):
                result[key] = [int(x) for x in val if isinstance(x, int)]
        return result

    def inject_basetopic(self, basetopic: str) -> None:
        """Inject the global basetopic into component models."""
        for component in self.switches.values():
            component.set_basetopic(basetopic)
