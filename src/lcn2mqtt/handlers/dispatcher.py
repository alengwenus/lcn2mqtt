"""Dispatcher for handling MQTT commands and routing them to the appropriate handlers."""

import re
from functools import wraps

from pypck import inputs

_MQTT_HANDLER_REGISTRY = []
_INPUT_HANDLER_REGISTRY = []


def mqtt_to_regex(pattern: str) -> str:
    pattern = pattern.replace("+", "[^/]+")
    pattern = pattern.replace("#", ".*")
    return "^" + pattern + "$"


def mqtt_handler(pattern: str):
    """Decorator to mark a method as an MQTT command handler for a specific topic pattern."""
    regex = mqtt_to_regex(pattern)

    def decorator(func):
        compiled = re.compile(regex)
        _MQTT_HANDLER_REGISTRY.append((compiled, func))

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def dispatch_mqtt(topic: str, payload, *args, **kwargs):
    """Dispatch an MQTT command to the appropriate handler based on the topic."""
    for pattern, func in _MQTT_HANDLER_REGISTRY:
        match = pattern.match(topic)
        if match:
            func(topic, payload, *args, **kwargs)


def input_handler(inp: inputs.Input):
    """Decorator to mark a method as an input handler."""

    def decorator(func):
        _INPUT_HANDLER_REGISTRY.append((inp, func))

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def dispatch_input(inp: inputs.Input, *args, **kwargs):
    """Dispatch an input command to the appropriate handler."""
    for registered_inp, func in _INPUT_HANDLER_REGISTRY:
        if isinstance(inp, registered_inp):
            func(inp, *args, **kwargs)
