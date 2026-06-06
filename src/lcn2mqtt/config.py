"""Configuration loaded from environment variables or a YAML file."""

from __future__ import annotations

import logging
import os
import re
from contextvars import ContextVar
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, field_validator, model_validator, PrivateAttr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from pypck.lcn_addr import LcnAddr

_LOG = logging.getLogger(__name__)

# Holds parsed YAML data for the duration of a load_config() call.
_yaml_ctx: ContextVar[dict[str, Any]] = ContextVar("_yaml_ctx", default={})


class _YamlSource(PydanticBaseSettingsSource):
    """Settings source that reads from the in-memory YAML context.

    *path* selects a nested section of the document, e.g. ``("lcn",)``
    for the ``lcn:`` block.  Dict-valued entries are skipped so that nested
    sub-configs always populate themselves through their own sources.
    """

    def __init__(self, settings_cls: type[BaseSettings], *path: str) -> None:
        super().__init__(settings_cls)
        self._path = path

    def _section(self) -> dict[str, Any]:
        data: Any = _yaml_ctx.get()
        for key in self._path:
            if not isinstance(data, dict):
                return {}
            data = data.get(key, {})
        return data if isinstance(data, dict) else {}

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        value = self._section().get(field_name)
        if isinstance(value, dict):
            value = None  # nested sub-configs handle themselves
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in self._section().items()
            if k in self.settings_cls.model_fields
            and v is not None
            and not isinstance(v, dict)
        }


class DevicesConfig(BaseModel):
    """Device attribute overrides parsed from LCN2MQTT_DEVICES_* environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    _module_overrides: dict[  # type: ignore[type-arg]
        tuple[int, int, bool], dict[str, Any]
    ] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _parse_module_overrides(self) -> "DevicesConfig":
        """Parse module overrides from YAML context and environment variables.

        YAML structure (lower priority):
            devices:
              m000007:
                output1:
                  transition: "10"   ->  module.output1.transition = "10"

        Env var pattern (higher priority):
            LCN2MQTT_DEVICES_{M|G}{SEG:03d}{ADDR:03d}_{HANDLER}{N}[_{ATTR}]=val
        """

        def _flatten(node: Any, parts: list[str]) -> dict[str, str]:
            """Recursively flatten a nested dict to {dot.path: str_value}."""
            if isinstance(node, dict):
                result: dict[str, str] = {}
                for k, v in node.items():
                    result.update(_flatten(v, parts + [str(k)]))
                return result
            return {".".join(parts): str(node)} if node is not None and parts else {}

        # 1. YAML context (lower priority)
        addr_re = re.compile(r"^(m|g)(\d{3})(\d{3})$", re.IGNORECASE)
        yaml_devices = _yaml_ctx.get().get("devices", {})
        if isinstance(yaml_devices, dict):
            for addr_str, handlers in yaml_devices.items():
                ma = addr_re.match(str(addr_str))
                if not ma or not isinstance(handlers, dict):
                    continue
                is_group = ma.group(1).lower() == "g"
                seg, addr = int(ma.group(2)), int(ma.group(3))
                lcn_addr = LcnAddr(seg, addr, is_group)
                for sub_path, val in _flatten(handlers, []).items():
                    self.add_override(lcn_addr, sub_path, val)

        # 2. Environment variables (higher priority, override YAML)
        pattern = re.compile(
            r"^LCN2MQTT_DEVICES_(M|G)(\d{3})(\d{3})((?:_[A-Z0-9]+)*)$",
            re.IGNORECASE,
        )
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
            seg_id = int(m.group(2))
            is_group = m.group(1).upper() == "G"
            addr_id = int(m.group(3))
            lcn_addr = LcnAddr(seg_id, addr_id, is_group)
            sub_part = m.group(4)[1:].lower().replace("_", ".")
            self.add_override(lcn_addr, sub_part, value)

        return self

    def add_override(self, lcn_addr: LcnAddr, sub_part: str, value: Any):
        """Add a single override (used for testing)."""
        _LOG.debug(
            "Module override queued: %s%03d%03d.%s=%r",
            "g" if lcn_addr.is_group else "m",
            lcn_addr.seg_id,
            lcn_addr.addr_id,
            sub_part,
            value,
        )
        self._module_overrides.setdefault(lcn_addr, {})[sub_part] = value

    @property
    def module_overrides(self) -> dict[LcnAddr, dict[str, Any]]:
        """Get the parsed module attribute overrides."""
        return self._module_overrides


class LcnConfig(BaseSettings):
    """LCN-PCHK connection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_LCN_",
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls, "lcn"),
            file_secret_settings,
        )


class MqttConfig(BaseSettings):
    """MQTT connection and topic configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_MQTT_",
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls, "mqtt"),
            file_secret_settings,
        )


class DiscoveryConfig(BaseSettings):
    """Home Assistant MQTT Discovery configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DISCOVERY_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = False
    prefix: str = "homeassistant"
    scan_modules: bool = True


class AppConfig(BaseSettings):
    """Main application configuration, including LCN and MQTT settings."""

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    lcn: LcnConfig = LcnConfig()
    mqtt: MqttConfig = MqttConfig()
    devices: DevicesConfig = DevicesConfig()
    discovery: DiscoveryConfig = DiscoveryConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls),  # reads from YAML root (scalars only)
            file_secret_settings,
        )

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert log level to uppercase."""
        return v.upper()


def load_config(
    yaml_file: str | os.PathLike = "data/configuration.yaml",
) -> AppConfig:
    """Load configuration from environment variables and an optional YAML file.

    Priority (highest to lowest):
    1. Environment variables (and .env file)
    2. configuration.yaml
    3. Built-in defaults

    The YAML file mirrors the environment-variable nesting::

        log_level: INFO
        lcn:
          host: 192.168.1.1
          port: 4114
          username: admin
          password: secret
        mqtt:
          host: 192.168.1.2
          port: 1883
        devices:
          m000007:
            output1:
              transition: "10"
    """
    try:
        with open(yaml_file) as fh:
            yaml_data: Any = yaml.safe_load(fh)
    except FileNotFoundError:
        yaml_data = {}
    token = _yaml_ctx.set(yaml_data if isinstance(yaml_data, dict) else {})
    try:
        return AppConfig()
    finally:
        _yaml_ctx.reset(token)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    config = load_config(
        os.path.expanduser("~/workspaces/lcn2mqtt/data/configuration.yaml")
    )
    print(config.model_dump_json(indent=2))
    print(config.devices.module_overrides)
