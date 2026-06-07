"""Configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from dotenv import dotenv_values
from pydantic import PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG = logging.getLogger(__name__)


class LcnConfig(BaseSettings):
    """LCN-PCHK connection and module configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LCN_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str
    port: int = 4114
    username: str
    password: str
    dim_mode: str = "STEPS200"  # "STEPS50" or "STEPS200"
    sk_num_tries: int = 0
    acknowledge_commands: bool = False

    _module_overrides: dict[  # type: ignore[type-arg]
        tuple[int, int, bool], dict[str, Any]
    ] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _parse_module_overrides(self) -> "LcnConfig":
        """Parse module attribute overrides from environment variables.

        Pattern: LCN_CONFIG_{M|G}{SEG:03d}{ADDR:03d}_{HANDLER}{N}[_{ATTR}]=val
        Example:  LCN_CONFIG_M000007_OUTPUT1_TRANSITION=10
                  -> module.output1.transition = 10
        """
        pattern = re.compile(
            r"^LCN_CONFIG_(M|G)(\d{3})(\d{3})_([A-Z]+)(\d+)((?:_[A-Z0-9]+)*)$",
            re.IGNORECASE,
        )
        overrides: dict[tuple[int, int, bool], dict[str, Any]] = {}
        env_file = self.model_config.get("env_file", ".env")
        if isinstance(env_file, (str, os.PathLike)):
            file_vars: dict[str, str | None] = dotenv_values(env_file)
        else:
            file_vars = {}
        env: dict[str, str] = {
            k: v for k, v in {**file_vars, **os.environ}.items() if v is not None
        }
        for key, value in env.items():
            m = pattern.match(key.upper())
            if m is None:
                continue
            seg = int(m.group(2))
            is_group = m.group(1).upper() == "G"
            addr = int(m.group(3))
            handler = m.group(4).lower()
            num = int(m.group(5))
            sub_parts = [p.lower() for p in m.group(6).split("_") if p]
            addr_key = (seg, addr, is_group)
            if addr_key not in overrides:
                overrides[addr_key] = {}
            field = f"{handler}{num}"
            field_path = ".".join([field] + sub_parts)
            overrides[addr_key][field_path] = value
            _LOG.debug(
                "Module override queued: %s -> %s%03d%03d.%s=%r",
                key,
                "g" if is_group else "m",
                seg,
                addr,
                field_path,
                value,
            )
        self._module_overrides = overrides
        return self

    @property
    def module_overrides(self) -> dict[tuple[int, int, bool], dict[str, Any]]:
        """Get the parsed module attribute overrides."""
        return self._module_overrides


class MqttConfig(BaseSettings):
    """MQTT connection and topic configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MQTT_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_topic: str = "lcn2mqtt"
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    qos: int = 0


class AppConfig(BaseSettings):
    """Main application configuration, including LCN and MQTT settings."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    lcn: LcnConfig = LcnConfig()
    mqtt: MqttConfig = MqttConfig()

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert log level to uppercase."""
        return v.upper()


def load_config() -> AppConfig:
    """Load the application configuration from environment variables and .env file."""
    return AppConfig()
