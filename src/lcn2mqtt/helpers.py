"""Helper functions for LCN2MQTT."""

from dataclasses import dataclass


@dataclass
class MqttMessage:
    """Represents an MQTT message with a topic and payload."""

    topic: str
    payload: str | None


def normalize_def_names(name: str) -> str:
    """Normalize LCN definition names."""
    if not isinstance(name, str):
        return name
    return name.lower().replace("variable", "var").replace("threshold", "thrs")
