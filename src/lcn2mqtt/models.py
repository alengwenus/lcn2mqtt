from typing import Annotated
from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict


class RelayState(StrEnum):
    ON = "on"
    OFF = "off"


class LedState(StrEnum):
    ON = "on"
    OFF = "off"
    BLINK = "blink"
    FLICKER = "flicker"


class MotorState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    OPENING = "opening"
    CLOSING = "closing"
    STOP = "stop"


VariableValue = Annotated[int | None, Field(ge=0)]
MotorValue = Annotated[float | None, Field(ge=0, le=100)]


class ModuleSerials(BaseModel):
    hardware: int
    software: int
    manu: int
    type: int


class Motor(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    state: MotorState | None = None
    position: MotorValue = None
    tilt: MotorValue = None


class Module(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    serials: ModuleSerials | None = None

    output1: float | None = Field(default=None, ge=0, le=100)
    output2: float | None = Field(default=None, ge=0, le=100)
    output3: float | None = Field(default=None, ge=0, le=100)
    output4: float | None = Field(default=None, ge=0, le=100)

    relay1: RelayState | None = None
    relay2: RelayState | None = None
    relay3: RelayState | None = None
    relay4: RelayState | None = None
    relay5: RelayState | None = None
    relay6: RelayState | None = None
    relay7: RelayState | None = None
    relay8: RelayState | None = None

    motor1: Motor | None = None
    motor2: Motor | None = None
    motor3: Motor | None = None
    motor4: Motor | None = None

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

    var1: VariableValue = None
    var2: VariableValue = None
    var3: VariableValue = None
    var4: VariableValue = None
    var5: VariableValue = None
    var6: VariableValue = None
    var7: VariableValue = None
    var8: VariableValue = None
    var9: VariableValue = None
    var10: VariableValue = None
    var11: VariableValue = None
    var12: VariableValue = None

    def update_output(self, output_number: int, value: float) -> bool:
        if not hasattr(self, f"output{output_number}"):
            raise ValueError(f"Invalid output number: {output_number}")
        current = getattr(self, f"output{output_number}")
        if current != value:
            setattr(self, f"output{output_number}", value)
            return True
        return False

    def update_relays(self, states: list[RelayState]) -> list[bool]:
        if len(states) != 8:
            raise ValueError(f"Invalid number of relay states: {len(states)}")
        changed = [False] * 8
        for i in range(1, 9):
            if getattr(self, f"relay{i}") != states[i - 1]:
                setattr(self, f"relay{i}", states[i - 1])
                changed[i - 1] = True
        return changed

    def update_motors(self, motors: list[Motor]) -> list[bool]:
        if len(motors) != 4:
            raise ValueError(f"Invalid number of motors: {len(motors)}")
        changed = [False] * 4
        for i in range(1, 5):
            if getattr(self, f"motor{i}") != motors[i - 1]:
                setattr(self, f"motor{i}", motors[i - 1])
                changed[i - 1] = True
        return changed

    def update_leds(self, states: list[LedState]) -> list[bool]:
        if len(states) != 12:
            raise ValueError(f"Invalid number of LED states: {len(states)}")
        changed = [False] * 12
        for i in range(1, 13):
            if getattr(self, f"led{i}") != states[i - 1]:
                setattr(self, f"led{i}", states[i - 1])
                changed[i - 1] = True
        return changed

    def update_variable(self, variable_number: int, value: int) -> bool:
        if not hasattr(self, f"var{variable_number}"):
            raise ValueError(f"Invalid variable number: {variable_number}")
        if getattr(self, f"var{variable_number}") != value:
            setattr(self, f"var{variable_number}", value)
            return True
        return False
