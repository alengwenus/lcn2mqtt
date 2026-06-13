"""Configuration loaded from environment variables or a YAML file."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, ClassVar
import json

import yaml
from dotenv import dotenv_values
from pydantic import ConfigDict, Field, field_validator, model_validator, BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from pypck.lcn_addr import LcnAddr

_LOG = logging.getLogger(__name__)


class CustomizedSourcesBaseSettings(BaseSettings):
    """BaseSettings subclass that allows customizing settings sources via settings_customise_sources()."""

    path: ClassVar[str] = ""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    _yaml_data: ClassVar[dict[str, Any]] = {}

    def __new__(
        cls, yaml_file: str | os.PathLike = "data/configuration.yaml", *args, **kwargs
    ):
        """Load YAML data once when the first instance is created."""
        try:
            with open(yaml_file) as fh:
                cls._yaml_data: Any = yaml.safe_load(fh)
        except FileNotFoundError:
            cls._yaml_data = {}

        return super().__new__(cls, *args, **kwargs)

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
            _YamlSource(settings_cls, cls._yaml_data, cls.path),
            file_secret_settings,
        )


class _YamlSource(PydanticBaseSettingsSource):
    """Settings source that reads from the in-memory YAML context.

    *path* selects a nested section of the document, e.g. ``("lcn",)``
    for the ``lcn:`` block.  Dict-valued entries are skipped so that nested
    sub-configs always populate themselves through their own sources.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], yaml_data: dict[str, Any], path: str
    ) -> None:
        super().__init__(settings_cls)

        if not isinstance(yaml_data, dict):
            yaml_data = {}

        section = yaml_data.get(path, yaml_data) if path != "" else yaml_data
        self._section: dict[str, Any] = section if isinstance(section, dict) else {}

    def get_field_value(self, field: Any, field_name: str):
        value = self._section.get(field_name)
        return (None if isinstance(value, dict) else value), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self._section.items()
            # if key in self.settings_cls.model_fields
            if value is not None and not isinstance(value, dict)
        }


class HomeAssistantModuleDiscoveryConfig(BaseModel):
    """Home Assistant discovery configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="allow")

    include: dict[str, list[int]] = {}
    exclude: dict[str, list[int]] = {}

    @field_validator("include", "exclude", mode="before")
    @classmethod
    def parse_list(cls, value: dict[str, list[int]]) -> dict[str, list[int]]:
        """Parse comma-separated strings into lists of ints."""
        result: dict[str, list[int]] = {}
        for key, val in value.items():
            if isinstance(val, str):
                result[key] = json.loads(val.strip("'"))
            elif isinstance(val, list):
                result[key] = [int(x) for x in val if isinstance(x, int)]
        return result


class DeviceConfig(BaseModel):
    """Configuration for a single LCN module/device."""

    module_overrides: dict[str, Any] = {}
    homeassistant: HomeAssistantModuleDiscoveryConfig = Field(
        default_factory=HomeAssistantModuleDiscoveryConfig
    )

    def add_override(self, sub_part: str, value: Any):
        """Add a single override (used for testing)."""
        if sub_part.startswith("homeassistant"):
            return
        self.module_overrides[sub_part] = value


class LcnConfig(CustomizedSourcesBaseSettings):
    """LCN-PCHK connection configuration."""

    path: ClassVar[str] = "lcn"

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_LCN_",
    )

    host: str
    port: int = 4114
    username: str
    password: str
    dim_mode: str = "STEPS200"  # "STEPS50" or "STEPS200"
    sk_num_tries: int = 0
    acknowledge_commands: bool = False


class MqttConfig(CustomizedSourcesBaseSettings):
    """MQTT connection and topic configuration."""

    path: ClassVar[str] = "mqtt"

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_MQTT_",
    )

    base_topic: str = "lcn2mqtt"
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    qos: int = 0


class DiscoveryConfig(CustomizedSourcesBaseSettings):
    """Home Assistant MQTT Discovery configuration."""

    path: ClassVar[str] = "homeassistant"
    model_config = SettingsConfigDict(
        env_prefix="HOMEASSISTANT_",
    )

    enabled: bool = False
    prefix: str = "homeassistant"
    scan_modules: bool = True


class AppConfig(CustomizedSourcesBaseSettings):
    """Main application configuration, including LCN and MQTT settings."""

    path: ClassVar[str] = ""
    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_",
    )

    log_level: str = "INFO"
    lcn: LcnConfig = Field(default_factory=LcnConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    devices: dict[LcnAddr, DeviceConfig] = Field(default_factory=dict)
    homeassistant: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert log level to uppercase."""
        return v.upper()

    @model_validator(mode="after")
    def _parse_devices(self) -> "AppConfig":
        """Parse module overrides from YAML context and environment variables.

        YAML structure (lower priority):
            devices:
              m000007:
                output1:
                  transition: "10"   ->  module.output1.transition = "10"

                homeassistant:
                  ...

        Env var pattern (higher priority):
            LCN2MQTT_DEVICES_{M|G}{SEG:03d}{ADDR:03d}_{HANDLER}{N}[_{ATTR}]=val
        """

        # if self._parsed:
        #     return self
        # self._parsed = True
        def _flatten(node: Any, parts: list[str]) -> dict[str, str]:
            """Recursively flatten a nested dict to {dot.path: str_value}."""
            if isinstance(node, dict):
                result: dict[str, str] = {}
                for key, value in node.items():
                    result.update(_flatten(value, parts + [str(key)]))
                return result
            return {".".join(parts): str(node)} if node is not None and parts else {}

        def set_nested(data: dict, key: str, value: object) -> None:
            """Set a value in a nested dict using a dot-separated key."""
            parts = key.lower().split(".")

            current = data
            for part in parts[:-1]:
                current = current.setdefault(part, {})

            current[parts[-1]] = value

        ha_handlers: dict[LcnAddr, dict[str, Any]] = {}
        overrides: dict[LcnAddr, dict[str, Any]] = {}

        # 1. YAML context (lower priority)
        addr_re = re.compile(r"^(m|g)(\d{3})(\d{3})$", re.IGNORECASE)
        yaml_devices = self._yaml_data.get("devices", {})
        if isinstance(yaml_devices, dict):
            for addr_str, handlers in yaml_devices.items():
                ma = addr_re.match(str(addr_str))
                if not ma or not isinstance(handlers, dict):
                    continue
                lcn_addr = LcnAddr.from_string(addr_str)
                self.devices[lcn_addr] = DeviceConfig()
                ha_handlers |= {
                    lcn_addr: handlers.pop("homeassistant", {})
                }  # skip homeassistant section for overrides
                overrides[lcn_addr] = _flatten(handlers, [])

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
            key: value
            for key, value in {**file_vars, **os.environ}.items()
            if value is not None
        }

        for key, value in env.items():
            m = pattern.match(key.upper())
            if m is None:
                continue
            seg_id = int(m.group(2))
            is_group = m.group(1).upper() == "G"
            addr_id = int(m.group(3))
            lcn_addr = LcnAddr(seg_id, addr_id, is_group)
            self.devices.setdefault(lcn_addr, DeviceConfig())
            sub_part = m.group(4)[1:].lower().replace("_", ".")
            if sub_part.startswith("homeassistant"):
                ha_sub_part = sub_part[len("homeassistant.") :].lower()
                set_nested(ha_handlers.setdefault(lcn_addr, {}), ha_sub_part, value)
            overrides.setdefault(lcn_addr, {})[sub_part] = value

        for lcn_addr, override in overrides.items():
            for sub_part, value in override.items():
                self.devices[lcn_addr].add_override(sub_part, value)

        for lcn_addr, ha_handler in ha_handlers.items():
            self.devices[
                lcn_addr
            ].homeassistant = HomeAssistantModuleDiscoveryConfig.model_validate(
                ha_handler
            )

        return self


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
    return AppConfig(yaml_file=yaml_file)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    config = load_config(
        os.path.expanduser("~/workspaces/lcn2mqtt/data/configuration.yaml")
    )
    print(config.model_dump_json(indent=2))
    # for addr, device in config.devices.items():
    #     print(device)
    #     print(device.module_overrides)
    #     print(device.homeassistant)
