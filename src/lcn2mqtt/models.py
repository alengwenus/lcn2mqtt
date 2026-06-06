"""Data models for LCN modules."""

from typing import Annotated
from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict, field_validator

from pypck import lcn_defs


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

    hardware: int | None = None
    software: int | None = None
    manu: int | None = None
    type: lcn_defs.HardwareType | None = None


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


class Motor(BaseModel):
    """Motor model for module motors."""

    model_config = ConfigDict(validate_assignment=True)

    state: MotorState | None = None
    position: MotorValue = None
    tilt: MotorValue = None


class Module(BaseModel):
    """Model for an LCN module."""

    model_config = ConfigDict(validate_assignment=True)

    serials: ModuleSerials = ModuleSerials()

    output1: Output = Output()
    output2: Output = Output()
    output3: Output = Output()
    output4: Output = Output()

    relay1: RelayState | None = None
    relay2: RelayState | None = None
    relay3: RelayState | None = None
    relay4: RelayState | None = None
    relay5: RelayState | None = None
    relay6: RelayState | None = None
    relay7: RelayState | None = None
    relay8: RelayState | None = None

    motor1: Motor = Motor()
    motor2: Motor = Motor()
    motor3: Motor = Motor()
    motor4: Motor = Motor()

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

    variable1: Variable = Variable()
    variable2: Variable = Variable()
    variable3: Variable = Variable()
    variable4: Variable = Variable()
    variable5: Variable = Variable()
    variable6: Variable = Variable()
    variable7: Variable = Variable()
    variable8: Variable = Variable()
    variable9: Variable = Variable()
    variable10: Variable = Variable()
    variable11: Variable = Variable()
    variable12: Variable = Variable()

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
