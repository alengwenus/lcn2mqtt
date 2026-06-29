"""Dispatcher for handling MQTT commands and routing them to the appropriate handlers."""

import re
from functools import wraps
from typing import AsyncGenerator

from pypck import inputs

from lcn2mqtt.helpers import MqttMessage

_MQTT_HANDLER_REGISTRY = []
_INPUT_HANDLER_REGISTRY = []


def mqtt_to_regex(pattern: str) -> str:
    pattern = pattern.replace("+", "[^/]+")
    pattern = pattern.replace("#", ".*")
    return "^" + pattern + "$"


def mqtt_handler(*pattern: str):
    """Decorator to mark a method as an MQTT command handler for a specific topic pattern."""
    regexes = [mqtt_to_regex(pat) for pat in pattern]

    def decorator(func):
        for regex in regexes:
            compiled = re.compile(regex)
            _MQTT_HANDLER_REGISTRY.append((compiled, func))

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


async def dispatch_mqtt(topic: str, payload, *args, **kwargs) -> bool:
    """Dispatch an MQTT command to the appropriate handler based on the topic."""
    success = False
    for pattern, func in _MQTT_HANDLER_REGISTRY:
        match = pattern.match(topic)
        if match:
            await func(topic, payload, *args, **kwargs)
            success = True
    return success


def input_handler(inp: inputs.Input):
    """Decorator to mark a method as an input handler."""

    def decorator(func):
        _INPUT_HANDLER_REGISTRY.append((inp, func))

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


async def dispatch_input(
    inp: inputs.Input, *args, **kwargs
) -> AsyncGenerator[MqttMessage]:
    """Dispatch an input command to the appropriate handler."""
    for registered_inp, func in _INPUT_HANDLER_REGISTRY:
        if isinstance(inp, registered_inp):
            messages: list[MqttMessage] = await func(inp, *args, **kwargs)
            for message in messages:
                yield message
