"""Models for components."""

from abc import abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypck.lcn_addr import LcnAddr
from pypck.lcn_defs import OutputPort, RelayPort


def set_if_none(value: Any, default: Any) -> Any:
    """Set value to default if it is None."""
    return value if value is not None else default


class BaseComponentModel(BaseModel):
    """Base model for Home Assistant components."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    address: LcnAddr = Field(..., exclude=True)
    basetopic: str = Field(default="lcn2mqtt", exclude=True)
    identifier: str = Field(..., exclude=True)

    unique_id: str | None = Field(default=None, alias="uniq_id")
    name: str | None = Field(default=None)

    # platform is set in subclasses and used for validation

    @property
    def prefix(self) -> str:
        """MQTT topic prefix for this component."""
        return (
            f"{self.basetopic}/module/{self.address.seg_id:d}/{self.address.addr_id:d}"
        )

    # @field_validator("*", mode="before")
    # @classmethod
    # def lower(cls, value: Any) -> Any:
    #     """Convert string fields to lowercase."""
    #     if isinstance(value, str):
    #         return value.lower()
    #     return value

    @model_validator(mode="after")
    def set_name(self) -> "BaseComponentModel":
        """Set default name if not provided."""
        if self.name is None:
            self.name = self.identifier.replace("_", " ").capitalize()
        return self

    def set_basetopic(self, basetopic: str) -> None:
        """Set the basetopic and update topics accordingly."""
        self.basetopic = basetopic
        self.set_unique_id()
        self.set_topics()

    def set_unique_id(self) -> None:
        """Set the unique ID and update topics accordingly."""
        if self.unique_id is None:
            self.unique_id = (
                f"{self.basetopic}_{self.address}_{self.platform}_{self.identifier}"
            )

    def discovery_info(self) -> dict[str, dict[str, Any]]:
        """Return discovery info for this component."""
        return self.model_dump(exclude_none=True)

    @abstractmethod
    def set_topics(self) -> None:
        """Set default topics."""


class SwitchComponent(BaseComponentModel):
    """Home Assistant switch component."""

    target: OutputPort | RelayPort = Field(..., exclude=True)

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
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        idx = int(self.target.value) + 1
        if isinstance(self.target, RelayPort):
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/relay/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/relay/{idx}/set"
            )
        elif isinstance(self.target, OutputPort):
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/output/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/output/{idx}/set"
            )


if __name__ == "__main__":
    lcn_addr = LcnAddr(0, 7, False)
    basetopic = "lcn2mqtt"
    switch = SwitchComponent(
        address=lcn_addr, basetopic=basetopic, target="relay1", identifier="test"
    )
    print(switch.model_dump_json(exclude_none=True, indent=2))
