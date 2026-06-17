"""Configuration loaded from environment variables or a YAML file."""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from pypck.lcn_addr import LcnAddr

from lcn2mqtt.homeassistant.module_config import HomeAssistantModuleDiscoveryConfig
from lcn2mqtt.module import Module

_LOG = logging.getLogger(__name__)


def flatten_with_values(data: dict[str, Any], prefix="") -> list[tuple[str, Any]]:
    """Flatten a nested dictionary into a list of (path, value) pairs."""
    items: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            items.extend(flatten_with_values(value, path))
        else:
            items.append((path, value))
    return items


class DeviceConfig(Module):
    """Configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="forbid")

    homeassistant: HomeAssistantModuleDiscoveryConfig = Field(
        default_factory=HomeAssistantModuleDiscoveryConfig
    )

    @model_validator(mode="before")
    @classmethod
    def configure_homeassistant(cls, data: Any) -> Any:
        if "homeassistant" not in data or not isinstance(data["homeassistant"], dict):
            data["homeassistant"] = {}

        data["homeassistant"].setdefault("address", data["address"])
        return data


class LcnConfig(BaseModel):
    """LCN-PCHK connection configuration."""

    host: str
    port: int = 4114
    username: str
    password: str
    dim_mode: str = "STEPS200"  # "STEPS50" or "STEPS200"
    sk_num_tries: int = 0
    acknowledge_commands: bool = False


class MqttConfig(BaseModel):
    """MQTT connection and topic configuration."""

    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    qos: int = 0

    _basetopic: str = PrivateAttr(default="lcn2mqtt")

    @property
    def basetopic(self) -> str:
        """MQTT topic prefix for all components."""
        return self._basetopic


class DiscoveryConfig(BaseModel):
    """Home Assistant MQTT Discovery configuration."""

    enabled: bool = False
    prefix: str = "homeassistant"
    scan_modules: bool = True


class AppConfig(BaseSettings):
    """Main application configuration, including LCN and MQTT settings."""

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
        case_sensitive=False,
        extra="ignore",
    )

    identifier: str = "lcn2mqtt"
    log_level: str = "INFO"
    lcn: LcnConfig = Field(default_factory=LcnConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    devices: dict[LcnAddr, DeviceConfig] = Field(default_factory=dict)
    homeassistant: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    def __new__(
        cls, yaml_file: str | os.PathLike = "data/configuration.yaml", *args, **kwargs
    ):
        """Pass the YAML file path to the base class for loading"""
        cls.model_config["yaml_file"] = yaml_file
        return super().__new__(cls, *args, **kwargs)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert log level to uppercase."""
        return v.upper()

    @model_validator(mode="after")
    def set_basetopic(self) -> AppConfig:
        """Inject the global basetopic into device configs."""
        self.mqtt._basetopic = self.identifier
        for device in self.devices.values():
            device.homeassistant.inject_basetopic(self.identifier)
        return self

    @model_validator(mode="before")
    @classmethod
    def to_lcn_addr(cls, data: Any) -> Any:
        if "devices" not in data or not isinstance(data["devices"], dict):
            data["devices"] = {}

        devices = {}

        for addr_str, device in data["devices"].items():
            lcn_addr = LcnAddr.from_string(addr_str)
            if device is None:
                device = {}

            device["address"] = lcn_addr
            devices[lcn_addr] = device

            flattened = flatten_with_values(
                {
                    key: value
                    for key, value in device.items()
                    if key in Module.model_fields
                }
            )
            for path, value in flattened:
                _LOG.info(
                    "Applied override %s.%s=%r",
                    lcn_addr.to_string(),
                    path,
                    value,
                )

        data["devices"] = devices
        return data

    def create_device_config(self, lcn_addr: LcnAddr) -> DeviceConfig:
        """Create a DeviceConfig for the given LCN address, applying overrides."""
        device_config = self.devices.get(lcn_addr)
        if device_config is not None:
            raise ValueError(f"Device config for {lcn_addr.to_string()} already exists")

        homeassistant_config = HomeAssistantModuleDiscoveryConfig(address=lcn_addr)
        device_config = DeviceConfig(
            address=lcn_addr, homeassistant=homeassistant_config
        )

        return device_config

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
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_config(
    yaml_file: str | os.PathLike = "data/configuration.yaml",
) -> AppConfig:
    """Load configuration from the specified YAML file and environment variables."""
    return AppConfig(yaml_file=yaml_file)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    config = load_config(
        os.path.expanduser("~/workspaces/lcn2mqtt/data/configuration.yaml")
    )
    print(config.model_dump_json(indent=2))
    print(config.mqtt.basetopic)
    print(type(list(config.devices.values())[0].homeassistant))
    # for addr, device in config.devices.items():
    #     print(device)
    #     print(device.module_overrides)
    #     print(device.homeassistant)
