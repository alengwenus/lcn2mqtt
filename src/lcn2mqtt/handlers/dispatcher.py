"""Dispatcher for handling MQTT commands and routing them to the appropriate handlers."""

import re
from functools import wraps

_HANDLER_REGISTRY = []


def mqtt_to_regex(pattern: str) -> str:
    pattern = pattern.replace("+", "[^/]+")
    pattern = pattern.replace("#", ".*")
    return "^" + pattern + "$"


def mqtt_handler(pattern: str):
    """Decorator to mark a method as an MQTT command handler for a specific topic pattern."""
    regex = mqtt_to_regex(pattern)

    def decorator(func):
        compiled = re.compile(regex)
        _HANDLER_REGISTRY.append((compiled, func))

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def dispatch(topic: str, payload, *args, **kwargs):
    """Dispatch an MQTT command to the appropriate handler based on the topic."""
    for pattern, func in _HANDLER_REGISTRY:
        match = pattern.match(topic)
        if match:
            func(topic, payload, *args, **kwargs)
