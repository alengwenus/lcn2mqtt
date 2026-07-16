"""Helper functions for LCN2MQTT."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any


@dataclass
class MqttMessage:
    """Represents an MQTT message with a topic and payload."""

    topic: str
    payload: str | None


@dataclass
class DeferredMqttMessage(MqttMessage):
    """An MqttMessage that is published after a delay.

    The bridge uses (module_address, topic) as an implicit cancel key: scheduling a new
    DeferredMqttMessage for the same topic automatically cancels the previous pending one.
    delay=None means cancel only – do not reschedule.
    """

    delay: float | None = None


def singleflight[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Ensure that only one instance of a function with the same arguments runs at a time.

    Should be used as a decorator.
    If the function is called again with the same arguments while it is still running, the subsequent calls
    will wait for the first call to complete and return the same result.
    """
    tasks: dict[
        tuple[tuple[Any, ...], tuple[tuple[str, Any], ...]], asyncio.Task[R]
    ] = {}

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        key = (args, tuple(sorted(kwargs.items())))

        if key not in tasks:
            task = asyncio.create_task(func(*args, **kwargs))
            task.add_done_callback(lambda _: tasks.pop(key, None))
            tasks[key] = task

        return await tasks[key]

    return wrapper
