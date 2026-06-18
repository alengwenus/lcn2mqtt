"""Data models for LCN modules."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pypck import lcn_defs
from pypck.device import DeviceConnection
from pypck.lcn_addr import LcnAddr


def alias_property(target: str):
    """Create a property that aliases another attribute."""
    return property(
        lambda self: getattr(self, target),
        lambda self, value: setattr(self, target, value),
    )


class OutputState(StrEnum):
    """State for module outputs."""

    ON = "on"
    OFF = "off"


class RelayState(StrEnum):
    """State for module relays."""

    ON = "on"
    OFF = "off"


class LedState(StrEnum):
    """State for module LEDs."""

    ON = "on"
    OFF = "off"
    BLINK = "blink"
    FLICKER = "flicker"


class MotorState(StrEnum):
    """State for module motors."""

    OPEN = "open"
    CLOSED = "closed"
    OPENING = "opening"
    CLOSING = "closing"
    STOP = "stop"


VariableValue = Annotated[int | None, Field(ge=0)]
MotorValue = Annotated[float | None, Field(ge=0, le=100)]


class ModuleSerials(BaseModel):
    """Serial numbers and type information for a module."""

    hardware: int = -1
    software: int = -1
    manu: int = -1
    type: lcn_defs.HardwareType = lcn_defs.HardwareType.UNKNOWN


class Output(BaseModel):
    """Output model for dimmable outputs."""

    model_config = ConfigDict(validate_assignment=True)

    state: OutputState | None = None
    brightness: float | None = Field(default=None, ge=0, le=100)  # percent
    transition: int | None = Field(default=None, ge=0)  # ms

    def update_state(self, state: OutputState) -> bool:
        """Update the output state and return True if it changed."""
        if self.state != state:
            self.state = state
            return True
        return False

    def update_brightness(self, value: float) -> bool:
        """Update the output brightness and return True if it changed."""
        if self.brightness != value:
            self.brightness = value
            return True
        return False


class Variable(BaseModel):
    """Variable model for module variables."""

    model_config = ConfigDict(validate_assignment=True)

    value: VariableValue = None  # native unit
    unit: lcn_defs.VarUnit = lcn_defs.VarUnit.NATIVE  # units for the variable
    locked: bool = False  # whether the variable is locked (for setpoints)

    @field_validator("unit", mode="before")
    @classmethod
    def _validate_unit(cls, v: str) -> lcn_defs.VarUnit:
        """Validate the variable unit."""
        try:
            unit = lcn_defs.VarUnit.parse(v.upper())
        except ValueError:
            raise ValueError(f"Invalid variable unit: {v}")
        return unit

    def update_value(self, value: int) -> bool:
        """Update a variable and return True if it changed."""
        if self.value != value:
            self.value = value
            return True
        return False

    def update_locked(self, locked: bool) -> bool:
        """Update the variable locked state and return True if it changed."""
        if self.locked != locked:
            self.locked = locked
            return True
        return False


class Motor(BaseModel):
    """Motor model for module motors."""

    model_config = ConfigDict(validate_assignment=True)

    state: MotorState | None = None
    position: MotorValue = None
    tilt: MotorValue = None


class Module(BaseModel):
    """Model for an LCN module."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    device_connection: DeviceConnection | None = None
    address: LcnAddr
    serials: ModuleSerials = Field(default_factory=ModuleSerials)
    name: str = ""

    output1: Output = Field(default_factory=Output)
    output2: Output = Field(default_factory=Output)
    output3: Output = Field(default_factory=Output)
    output4: Output = Field(default_factory=Output)

    relay1: RelayState | None = None
    relay2: RelayState | None = None
    relay3: RelayState | None = None
    relay4: RelayState | None = None
    relay5: RelayState | None = None
    relay6: RelayState | None = None
    relay7: RelayState | None = None
    relay8: RelayState | None = None

    motor1: Motor = Field(default_factory=Motor)
    motor2: Motor = Field(default_factory=Motor)
    motor3: Motor = Field(default_factory=Motor)
    motor4: Motor = Field(default_factory=Motor)

    led1: LedState | None = None
    led2: LedState | None = None
    led3: LedState | None = None
    led4: LedState | None = None
    led5: LedState | None = None
    led6: LedState | None = None
    led7: LedState | None = None
    led8: LedState | None = None
    led9: LedState | None = None
    led10: LedState | None = None
    led11: LedState | None = None
    led12: LedState | None = None

    variable1: Variable = Field(default_factory=Variable)
    variable2: Variable = Field(default_factory=Variable)
    variable3: Variable = Field(default_factory=Variable)
    variable4: Variable = Field(default_factory=Variable)
    variable5: Variable = Field(default_factory=Variable)
    variable6: Variable = Field(default_factory=Variable)
    variable7: Variable = Field(default_factory=Variable)
    variable8: Variable = Field(default_factory=Variable)
    variable9: Variable = Field(default_factory=Variable)
    variable10: Variable = Field(default_factory=Variable)
    variable11: Variable = Field(default_factory=Variable)
    variable12: Variable = Field(default_factory=Variable)

    setpoint1: Variable = Field(default_factory=Variable)
    setpoint2: Variable = Field(default_factory=Variable)

    threshold11: Variable = Field(default_factory=Variable)
    threshold12: Variable = Field(default_factory=Variable)
    threshold13: Variable = Field(default_factory=Variable)
    threshold14: Variable = Field(default_factory=Variable)
    threshold15: Variable = Field(default_factory=Variable)
    threshold21: Variable = Field(default_factory=Variable)
    threshold22: Variable = Field(default_factory=Variable)
    threshold23: Variable = Field(default_factory=Variable)
    threshold24: Variable = Field(default_factory=Variable)
    threshold31: Variable = Field(default_factory=Variable)
    threshold32: Variable = Field(default_factory=Variable)
    threshold33: Variable = Field(default_factory=Variable)
    threshold34: Variable = Field(default_factory=Variable)
    threshold41: Variable = Field(default_factory=Variable)
    threshold42: Variable = Field(default_factory=Variable)
    threshold43: Variable = Field(default_factory=Variable)
    threshold44: Variable = Field(default_factory=Variable)

    threshold1 = alias_property("threshold11")
    threshold2 = alias_property("threshold12")
    threshold3 = alias_property("threshold13")
    threshold4 = alias_property("threshold14")
    threshold5 = alias_property("threshold15")

    def update_relays(self, states: list[RelayState]) -> list[bool]:
        """Update the relay states and return a list of which ones changed."""
        if len(states) != 8:
            raise ValueError(f"Invalid number of relay states: {len(states)}")
        changed = [False] * 8
        for i in range(1, 9):
            if getattr(self, f"relay{i}") != states[i - 1]:
                setattr(self, f"relay{i}", states[i - 1])
                changed[i - 1] = True
        return changed

    def update_motors(self, states: list[MotorState]) -> list[bool]:
        """Update the motor states and return a list of which ones changed."""
        if len(states) != 4:
            raise ValueError(f"Invalid number of motors: {len(states)}")
        changed = [False] * 4
        for i in range(1, 5):
            motor = getattr(self, f"motor{i}")
            if motor.state != states[i - 1]:
                motor.state = states[i - 1]
                changed[i - 1] = True
        return changed

    def update_leds(self, states: list[LedState]) -> list[bool]:
        """Update the LED states and return a list of which ones changed."""
        if len(states) != 12:
            raise ValueError(f"Invalid number of LED states: {len(states)}")
        changed = [False] * 12
        for i in range(1, 13):
            if getattr(self, f"led{i}") != states[i - 1]:
                setattr(self, f"led{i}", states[i - 1])
                changed[i - 1] = True
        return changed
