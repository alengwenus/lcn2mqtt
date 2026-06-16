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
        for identifier, component in data.get("switches", {}).items():
            if isinstance(component, dict):
                component["address"] = data["address"]
                component["identifier"] = identifier

        return data

    def inject_basetopic(self, basetopic: str) -> None:
        """Inject the global basetopic into component models."""
        for component in self.switches.values():
            component.set_basetopic(basetopic)
