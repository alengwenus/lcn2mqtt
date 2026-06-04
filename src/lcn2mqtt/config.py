"""Configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LcnConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LCN_", case_sensitive=False)

    host: str
    port: int = 4114
    username: str
    password: str
    name: str = "pchk"
    dim_mode: str = "STEPS200"  # "STEPS50" or "STEPS200"
    sk_num_tries: int = 0
    acknowledge_commands: bool = False

class MqttConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MQTT_", case_sensitive=False)

    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    qos: int = 0


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    log_level: str = "INFO"
    lcn: LcnConfig = LcnConfig()
    mqtt: MqttConfig = MqttConfig()

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


def load_config() -> AppConfig:
    return AppConfig()
