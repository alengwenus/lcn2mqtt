"""Models for components."""

from abc import abstractmethod
from itertools import chain
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypck import lcn_defs
from pypck.lcn_addr import LcnAddr


def set_if_none(value: Any, default: Any) -> Any:
    """Set value to default if it is None."""
    return value if value is not None else default


class BaseComponentModel(BaseModel):
    """Base model for Home Assistant components."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    address: LcnAddr | None = Field(default=None, exclude=True)
    base_topic: str = Field(default="lcn2mqtt", exclude=True)
    identifier: str | None = Field(default=None, exclude=True)

    unique_id: str | None = Field(default=None, alias="uniq_id")
    name: str | None = Field(default=None)

    # platform is set in subclasses and used for validation
    platform: Literal[None] = Field(..., alias="p")

    @property
    def prefix(self) -> str:
        """MQTT topic prefix for this component."""
        assert self.address is not None, "Address must be set before accessing prefix"
        return (
            f"{self.base_topic}/module/{self.address.seg_id:d}/{self.address.addr_id:d}"
        )

    def update_properties(self, address: LcnAddr, identifier: str) -> None:
        """Update properties based on the current address and identifier."""
        self.address = address
        self.identifier = identifier
        if self.name is None:
            self.name = identifier.replace("_", " ").capitalize()

    def update_base_topic(self, base_topic: str) -> None:
        """Set the base_topic and update topics accordingly."""
        self.base_topic = base_topic
        self.update_unique_id()
        self.update_topics()

    def update_unique_id(self) -> None:
        """Set the unique ID and update topics accordingly."""
        if self.unique_id is None:
            self.unique_id = (
                f"{self.base_topic}_{self.address}_{self.platform}_{self.identifier}"
            )

    def discovery_info(self) -> dict[str, Any]:
        """Return discovery info for this component."""
        return self.model_dump(exclude_none=True)

    @abstractmethod
    def update_topics(self) -> None:
        """Update default topics."""


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
            value = value.upper()
            if value in lcn_defs.RelayPort.__members__:
                value = lcn_defs.RelayPort[value]
            elif value in lcn_defs.OutputPort.__members__:
                value = lcn_defs.OutputPort[value]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def update_topics(self) -> None:
        """Update default topics."""
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

    def update_topics(self) -> None:
        """Update default topics."""
        super().update_topics()

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


class BinarySensorComponent(BaseComponentModel):
    """Home Assistant binary sensor component."""

    source: lcn_defs.BinSensorPort = Field(..., exclude=True)

    state_topic: str | None = None
    payload_on: str = "on"
    payload_off: str = "off"

    platform: Literal["binary_sensor"] = Field(default="binary_sensor", alias="p")  # type: ignore[assignment]

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> Any:
        """Validate the source."""
        if isinstance(value, str):
            value_upper = value.upper()
            if value_upper in lcn_defs.BinSensorPort.__members__:
                value = lcn_defs.BinSensorPort[value_upper]
            else:
                raise ValueError(f"Invalid source '{value}'.")
        return value

    def update_topics(self) -> None:
        """Update default topics."""
        self.state_topic = set_if_none(
            self.state_topic,
            f"{self.prefix}/binsensor/{int(self.source.value) + 1}/state",
        )


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
            value_upper = value.upper()
            if value_upper in lcn_defs.Var.__members__:
                return lcn_defs.Var[value_upper]
            elif value_upper in lcn_defs.LedPort.__members__:
                return lcn_defs.LedPort[value_upper]
            raise ValueError(f"Invalid source '{value}'.")
        return value

    def update_topics(self) -> None:
        """Update default topics."""
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
            value_upper = value.upper()
            if value_upper in lcn_defs.Var.__members__:
                var = lcn_defs.Var[value_upper]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return var

    def update_topics(self) -> None:
        """Update default topics."""
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
            value_upper = value.upper()
            if value_upper in lcn_defs.LedPort.__members__:
                value = lcn_defs.LedPort[value_upper]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def update_topics(self) -> None:
        """Update default topics."""
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
    state_open: str = "open"
    state_closed: str = "closed"
    state_opening: str = "opening"
    state_closing: str = "closing"
    state_stopped: str = "stopped"
    payload_open: str = "open"
    payload_close: str = "close"
    payload_stop: str = "stop"

    platform: Literal["cover"] = Field(default="cover", alias="p")  # type: ignore[assignment]

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> Any:
        """Validate the target."""
        if isinstance(value, str):
            value_upper = value.upper()
            if value_upper in lcn_defs.MotorPort.__members__:
                value = lcn_defs.MotorPort[value_upper]
            else:
                raise ValueError(f"Invalid target '{value}'.")
        return value

    def update_topics(self) -> None:
        """Update default topics."""
        if self.target == lcn_defs.MotorPort.OUTPUTS:
            port = "outputs"
        elif self.target in {
            lcn_defs.MotorPort.MOTOR1,
            lcn_defs.MotorPort.MOTOR2,
            lcn_defs.MotorPort.MOTOR3,
            lcn_defs.MotorPort.MOTOR4,
        }:
            port = str(int(self.target.value) + 1)
        else:
            return
        self.state_topic = set_if_none(
            self.state_topic, f"{self.prefix}/motor/{port}/state"
        )
        self.command_topic = set_if_none(
            self.command_topic, f"{self.prefix}/motor/{port}/set"
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
    mode_command_template: str = '{{ "off" if value=="heat" else "on" }}'
    mode_state_template: str = '{{ "heat" if value=="off" else "off" }}'
    modes: list[str] = ["off", "heat"]

    platform: Literal["climate"] = Field(default="climate", alias="p")  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def validate_temperature(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the temperature and current_temperature targets."""
        for field in ["temperature", "current_temperature"]:
            if field not in data:
                raise ValueError(f"'{field}' is required for climate components.")

        temperature_str = data["temperature"]
        if lcn_defs.Var.is_set_point(temperature_str):
            data["temperature"] = lcn_defs.Var[temperature_str.upper()]
        else:
            raise ValueError(f"Invalid temperature '{temperature_str}'.")

        current_temperature_str = data["current_temperature"]
        if lcn_defs.Var.is_variable(current_temperature_str):
            data["current_temperature"] = lcn_defs.Var[current_temperature_str.upper()]
        else:
            raise ValueError(
                f"Invalid current_temperature '{current_temperature_str}'."
            )

        return data

    def update_topics(self) -> None:
        """Update default topics."""
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
