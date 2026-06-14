"""Models for components."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypck.lcn_addr import LcnAddr
from pypck.lcn_defs import OutputPort, RelayPort


class BaseComponentModel(BaseModel):
    """Base model for Home Assistant components."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    address: LcnAddr = Field(..., exclude=True)
    base_topic: str = Field(..., exclude=True)
    target: OutputPort | RelayPort = Field(..., exclude=True)
    identifier: str = Field(..., exclude=True)

    unique_id: str | None = Field(default=None, alias="uniq_id")
    name: str | None = Field(default=None)

    # platform is set in subclasses and used for validation

    @property
    def prefix(self) -> str:
        """MQTT topic prefix for this component."""
        return f"{self.base_topic}/device/{self.address.to_string()}"

    @field_validator("*", mode="before")
    @classmethod
    def lower(cls, value: Any) -> Any:
        """Convert string fields to lowercase."""
        if isinstance(value, str):
            return value.lower()
        return value

    @model_validator(mode="after")
    def set_name(self) -> "BaseComponentModel":
        """Set default name if not provided."""
        if self.name is None:
            idx = int(self.target.value)
            self.name = f"{self.target.name.capitalize()[:-1]} {idx}"
        return self

    @model_validator(mode="after")
    def set_unique_id(self) -> "BaseComponentModel":
        """Set default unique_id if not provided."""
        if self.unique_id is None:
            self.unique_id = (
                f"lcn2mqtt_{self.address}_{self.platform}_{self.identifier}"
            )
        return self


class SwitchComponent(BaseComponentModel):
    """Home Assistant switch component."""

    state_topic: str | None = None
    command_topic: str | None = None
    payload_on: str = "on"
    payload_off: str = "off"
    state_on: str = "on"
    state_off: str = "off"

    platform: Literal["switch"] = Field(default="switch", alias="p")

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate that target is in the form 'relay1', 'output2', etc."""
        if isinstance(value, str):
            if value.upper() in RelayPort.__members__:
                value = RelayPort[value.upper()]
            elif value.upper() in OutputPort.__members__:
                value = OutputPort[value.upper()]
            else:
                raise ValueError(
                    f"Invalid target '{value}'. Must be 'relay1'-'relay8' or 'output1'-'output4'."
                )
        return value

    @model_validator(mode="after")
    def set_topics(self) -> "SwitchComponent":
        """Set default topics if not provided."""
        idx = int(self.target.value)
        if isinstance(self.target, RelayPort):
            self.state_topic = f"{self.prefix}/relay/{idx}/state"
            self.command_topic = f"{self.prefix}/relay/{idx}/set"
        elif isinstance(self.target, OutputPort):
            self.state_topic = f"{self.prefix}/output/{idx}/state"
            self.command_topic = f"{self.prefix}/output/{idx}/set"
        return self


if __name__ == "__main__":
    lcn_addr = LcnAddr(0, 7, False)
    base_topic = "lcn2mqtt"
    switch = SwitchComponent(
        address=lcn_addr, base_topic=base_topic, target="relay1", identifier="test"
    )
    print(switch.model_dump_json(exclude_none=True, indent=2))
