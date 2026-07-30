"""Dispatcher for handling MQTT commands and routing them to the appropriate handlers."""

import re
from collections.abc import Awaitable, Callable, Generator
from functools import wraps
from typing import TYPE_CHECKING, Any

from pypck import inputs

from lcn2mqtt.helpers import MqttMessage
from lcn2mqtt.models.device import Device

if TYPE_CHECKING:
    from lcn2mqtt.bridge import Bridge

_MQTT_HANDLER_REGISTRY: list[tuple[re.Pattern[str], Callable[..., Awaitable[Any]]]] = []
_INPUT_HANDLER_REGISTRY: list[
    tuple[type[inputs.Input], Callable[..., Generator[MqttMessage]]]
] = []


def mqtt_to_regex(pattern: str) -> str:
    """Convert an MQTT topic pattern to a regular expression."""
    pattern = pattern.replace("+", "[^/]+")
    pattern = pattern.replace("#", ".*")
    return "^" + pattern + "$"


def mqtt_handler(
    *pattern: str,
) -> Callable[..., Callable[..., Awaitable[Any]]]:
    """Decorate a method as an MQTT command handler for a specific topic pattern."""
    regexes = [mqtt_to_regex(pat) for pat in pattern]

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        for regex in regexes:
            compiled = re.compile(regex)
            _MQTT_HANDLER_REGISTRY.append((compiled, func))

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Awaitable[Any]:
            return func(*args, **kwargs)

        return wrapper

    return decorator


async def dispatch_mqtt(
    topic: str,
    payload: str,
    module: Device,
    bridge: Bridge,
    *args: Any,
    **kwargs: Any,
) -> bool:
    """Dispatch an MQTT command to the appropriate handler based on the topic."""
    success = False
    for pattern, func in _MQTT_HANDLER_REGISTRY:
        match = pattern.match(topic)
        if match:
            await func(topic, payload, module, bridge, *args, **kwargs)
            success = True
    return success


def input_handler(
    inp: type[inputs.Input],
) -> Callable[..., Callable[..., Generator[MqttMessage]]]:
    """Decorate a method as an input handler."""

    def decorator(
        func: Callable[..., Generator[MqttMessage]],
    ) -> Callable[..., Generator[MqttMessage]]:
        _INPUT_HANDLER_REGISTRY.append((inp, func))

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Generator[MqttMessage]:
            return func(*args, **kwargs)

        return wrapper

    return decorator


def dispatch_input(
    inp: inputs.Input, *args: Any, **kwargs: Any
) -> Generator[MqttMessage]:
    """Dispatch an input command to the appropriate handler."""
    for registered_inp, func in _INPUT_HANDLER_REGISTRY:
        if isinstance(inp, registered_inp):
            yield from func(inp, *args, **kwargs)
