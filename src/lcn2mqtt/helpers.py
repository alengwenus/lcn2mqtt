"""Helper functions for LCN2MQTT."""

from dataclasses import dataclass


@dataclass
class MqttMessage:
    """Represents an MQTT message with a topic and payload."""

    topic: str
    payload: str | None
