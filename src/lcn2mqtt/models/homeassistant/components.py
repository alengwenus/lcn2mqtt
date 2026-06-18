"""Models for components."""

from abc import abstractmethod
from itertools import chain
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypck.lcn_addr import LcnAddr
from pypck import lcn_defs

from ...helpers import normalize_def_names


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

    target: lcn_defs.OutputPort | lcn_defs.RelayPort = Field(..., exclude=True)

    state_topic: str | None = None
    command_topic: str | None = None
    payload_on: str = "on"
    payload_off: str = "off"
    state_on: str = "on"
    state_off: str = "off"

    platform: Literal["switch"] = Field(default="switch", alias="p")  # type: ignore[assignment]

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate that target is in the form 'relay1', 'output2', etc."""
        if isinstance(value, str):
            value = normalize_def_names(value)
            if value.upper() in lcn_defs.RelayPort.__members__:
                value = lcn_defs.RelayPort[value.upper()]
            elif value.upper() in lcn_defs.OutputPort.__members__:
                value = lcn_defs.OutputPort[value.upper()]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        idx = int(self.target.value) + 1
        if isinstance(self.target, lcn_defs.RelayPort):
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/relay/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/relay/{idx}/set"
            )
        elif isinstance(self.target, lcn_defs.OutputPort):
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/output/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/output/{idx}/set"
            )


class LightComponent(SwitchComponent):
    """Home Assistant light component."""

    brightness_state_topic: str | None = Field(default=None)
    brightness_command_topic: str | None = Field(default=None)
    brightness_scale: int | None = Field(default=None)

    platform: Literal["light"] = Field(default="light", alias="p")  # type: ignore[assignment]

    def set_topics(self):
        """Set default topics."""
        super().set_topics()

        if not isinstance(self.target, lcn_defs.OutputPort):
            return

        idx = int(self.target.value) + 1
        self.brightness_state_topic = set_if_none(
            self.brightness_state_topic, f"{self.prefix}/output/{idx}/brightness"
        )
        self.brightness_command_topic = set_if_none(
            self.brightness_command_topic, f"{self.prefix}/output/{idx}/set_brightness"
        )
        self.brightness_scale = set_if_none(self.brightness_scale, 100)


class SensorComponent(BaseComponentModel):
    """Home Assistant sensor component."""

    source: lcn_defs.Var | lcn_defs.LedPort = Field(..., exclude=True)

    state_topic: str | None = None

    platform: Literal["sensor"] = Field(default="sensor", alias="p")  # type: ignore[assignment]

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> Any:
        """Validate the source."""
        if isinstance(value, str):
            value = normalize_def_names(value)
            if value.upper().replace("VARIABLE", "VAR") in lcn_defs.Var.__members__:
                value = lcn_defs.Var[value.upper()]
            elif value.upper() in lcn_defs.LedPort.__members__:
                value = lcn_defs.LedPort[value.upper()]
            else:
                raise ValueError(f"Invalid source '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        if self.source in set(lcn_defs.Var.variables()):
            idx = lcn_defs.Var.to_var_id(self.source) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/variable/{idx}/state"
            )
        elif self.source in set(lcn_defs.Var.set_points()):
            idx = lcn_defs.Var.to_set_point_id(self.source) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/setpoint/{idx}/state"
            )
        elif self.source in set(chain.from_iterable(lcn_defs.Var.thresholds())):
            register = lcn_defs.Var.to_thrs_register_id(self.source) + 1
            idx = lcn_defs.Var.to_thrs_id(self.source) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/threshold/{register}/{idx}/state"
            )
        elif isinstance(self.source, lcn_defs.LedPort):
            idx = int(self.source.value) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/led/{idx}/state"
            )


class NumberComponent(BaseComponentModel):
    """Home Assistant number component."""

    target: lcn_defs.Var = Field(..., exclude=True)

    state_topic: str | None = None
    command_topic: str | None = None

    platform: Literal["number"] = Field(default="number", alias="p")  # type: ignore[assignment]

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate the target."""
        if isinstance(value, str):
            value = normalize_def_names(value)
            if value.upper() in lcn_defs.Var.__members__:
                value = lcn_defs.Var[value.upper()]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        if self.target in set(lcn_defs.Var.variables()):
            idx = lcn_defs.Var.to_var_id(self.target) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/variable/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/variable/{idx}/set"
            )
        elif self.target in set(lcn_defs.Var.set_points()):
            idx = lcn_defs.Var.to_set_point_id(self.target) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/setpoint/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/setpoint/{idx}/set"
            )
        elif self.target in set(chain.from_iterable(lcn_defs.Var.thresholds())):
            register = lcn_defs.Var.to_thrs_register_id(self.target) + 1
            idx = lcn_defs.Var.to_thrs_id(self.target) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/threshold/{register}/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/threshold/{register}/{idx}/set"
            )


class SelectComponent(BaseComponentModel):
    """Home Assistant select component."""

    target: lcn_defs.LedPort = Field(..., exclude=True)

    state_topic: str | None = None
    command_topic: str | None = None
    options: list[str] = [state.name.lower() for state in lcn_defs.LedStatus]

    platform: Literal["select"] = Field(default="select", alias="p")  # type: ignore[assignment]

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate the target."""
        if isinstance(value, str):
            value = normalize_def_names(value)
            if value.upper() in lcn_defs.LedPort.__members__:
                value = lcn_defs.LedPort[value.upper()]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        if isinstance(self.target, lcn_defs.LedPort):
            idx = int(self.target.value) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/led/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/led/{idx}/set"
            )


class CoverComponent(BaseComponentModel):
    """Home Assistant cover component."""

    target: lcn_defs.MotorPort = Field(..., exclude=True)

    state_topic: str | None = None
    command_topic: str | None = None

    platform: Literal["cover"] = Field(default="cover", alias="p")  # type: ignore[assignment]

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate the target."""
        if isinstance(value, str):
            value = normalize_def_names(value)
            if value.upper() in lcn_defs.MotorPort.__members__:
                value = lcn_defs.MotorPort[value.upper()]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def set_topics(self):
        """Set default topics."""
        if isinstance(self.target, lcn_defs.MotorPort):
            idx = int(self.target.value) + 1
            self.state_topic = set_if_none(
                self.state_topic, f"{self.prefix}/motor/{idx}/state"
            )
            self.command_topic = set_if_none(
                self.command_topic, f"{self.prefix}/motor/{idx}/set"
            )


class ClimateComponent(BaseComponentModel):
    """Home Assistant climate component."""

    temperature: lcn_defs.Var = Field(..., exclude=True)
    current_temperature: lcn_defs.Var = Field(..., exclude=True)

    temperature_state_topic: str | None = None
    temperature_command_topic: str | None = None
    current_temperature_topic: str | None = None
    mode_state_topic: str | None = None
    mode_command_topic: str | None = None
    mode_command_template: str = '{{ value if value=="off" else "on" }}'
    mode_state_template: str = '{{ "off" if value=="off" else "heat" }}'
    modes: list[str] = ["off", "heat"]

    platform: Literal["climate"] = Field(default="climate", alias="p")  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def validate_temperature(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the temperature and current_temperature targets."""
        for field in ["temperature", "current_temperature"]:
            if field not in data:
                raise ValueError(f"'{field}' is required for climate components.")

        temperature_str = normalize_def_names(data["temperature"]).upper()
        current_temperature_str = normalize_def_names(
            data["current_temperature"]
        ).upper()

        if temperature_str in (setpoint.name for setpoint in lcn_defs.Var.set_points()):
            data["temperature"] = lcn_defs.Var[temperature_str]
        else:
            raise ValueError(f"Invalid temperature '{temperature_str}'.")

        if current_temperature_str in (
            name
            for name in lcn_defs.Var.__members__
            if lcn_defs.Var[name] in lcn_defs.Var.variables()
        ):
            data["current_temperature"] = lcn_defs.Var[current_temperature_str]
        else:
            raise ValueError(
                f"Invalid current_temperature '{current_temperature_str}'."
            )

        return data

    def set_topics(self):
        """Set default topics."""
        temperature_idx = lcn_defs.Var.to_set_point_id(self.temperature) + 1
        self.temperature_state_topic = set_if_none(
            self.temperature_state_topic,
            f"{self.prefix}/setpoint/{temperature_idx}/state",
        )
        self.temperature_command_topic = set_if_none(
            self.temperature_command_topic,
            f"{self.prefix}/setpoint/{temperature_idx}/set",
        )

        current_temperature_idx = lcn_defs.Var.to_var_id(self.current_temperature) + 1
        self.current_temperature_topic = set_if_none(
            self.current_temperature_topic,
            f"{self.prefix}/variable/{current_temperature_idx}/state",
        )

        mode_idx = temperature_idx
        self.mode_state_topic = set_if_none(
            self.mode_state_topic, f"{self.prefix}/setpoint/{mode_idx}/locked"
        )
        self.mode_command_topic = set_if_none(
            self.mode_command_topic, f"{self.prefix}/setpoint/{mode_idx}/lock"
        )


if __name__ == "__main__":
    lcn_addr = LcnAddr(0, 7, False)
    basetopic = "lcn2mqtt"
    switch = SwitchComponent(
        address=lcn_addr, basetopic=basetopic, target="relay1", identifier="test"
    )
    print(switch.model_dump_json(exclude_none=True, indent=2))
