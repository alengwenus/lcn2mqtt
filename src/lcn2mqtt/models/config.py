"""Configuration loaded from environment variables or a YAML file."""

from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path
from typing import Any, Literal

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

from lcn2mqtt.models.device import Device
from lcn2mqtt.models.homeassistant.discovery import (
    HomeAssistantModuleDiscoveryConfig,
)

_LOG = logging.getLogger(__name__)


def flatten_with_values(
    data: dict[str, Any], prefix: str = ""
) -> list[tuple[str, Any]]:
    """Flatten a nested dictionary into a list of (path, value) pairs."""
    items: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            items.extend(flatten_with_values(value, path))
        else:
            items.append((path, value))
    return items


class DeviceConfig(Device):
    """Configuration for a single LCN module/device."""

    model_config = ConfigDict(extra="forbid")

    homeassistant: HomeAssistantModuleDiscoveryConfig = Field(
        default_factory=HomeAssistantModuleDiscoveryConfig
    )


class LcnConfig(BaseModel):
    """LCN-PCHK connection configuration."""

    host: str
    port: int = 4114
    username: str
    password: str
    dim_mode: str = "STEPS200"  # "STEPS50" or "STEPS200"
    sk_num_tries: int = 0
    acknowledge_commands: bool = False

    @field_validator("dim_mode", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert dim mode to uppercase."""
        return v.upper()


class MqttConfig(BaseModel):
    """MQTT connection and topic configuration."""

    base_topic: str = "lcn2mqtt"
    host: str
    port: int = 1883
    transport: Literal["tcp", "websockets", "unix"] = "tcp"
    username: str | None = None
    password: str | None = None
    qos: int = 0
    cafile: str | None = None
    _ssl_context: ssl.SSLContext | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _upper(self) -> MqttConfig:
        """Create SSLContext."""
        if self.cafile:
            self._ssl_context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH, cafile=self.cafile
            )
        return self

    @property
    def ssl_context(self) -> ssl.SSLContext | None:
        """Return the SSLContext."""
        return self._ssl_context


class DiscoveryConfig(BaseModel):
    """Home Assistant MQTT Discovery configuration."""

    enabled: bool = False
    prefix: str = "homeassistant"
    scan_modules: bool = True


class AppConfig(BaseSettings):
    """Main application configuration, including LCN and MQTT settings."""

    model_config = SettingsConfigDict(
        env_prefix="LCN2MQTT__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    log_level: str = "INFO"
    retained_broker_states: bool = True
    lcn: LcnConfig  # = Field(default_factory=LcnConfig)
    mqtt: MqttConfig  # = Field(default_factory=MqttConfig)
    devices: dict[LcnAddr, DeviceConfig] = Field(default_factory=dict)
    homeassistant: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    def __new__(
        cls,
        yaml_file: str | os.PathLike[str] = "data/configuration.yaml",
        *args: Any,
        **kwargs: Any,
    ) -> AppConfig:
        """Pass the YAML file path to the base class for loading."""
        cls.model_config["yaml_file"] = Path(yaml_file)
        return super().__new__(cls, *args, **kwargs)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Convert log level to uppercase."""
        return v.upper()

    @model_validator(mode="before")
    @classmethod
    def to_lcn_addr(cls, data: Any) -> Any:
        """Convert device addresses to LcnAddr instances."""
        if "devices" not in data or not isinstance(data["devices"], dict):
            data["devices"] = {}

        devices = {}

        for addr_str, device in data["devices"].items():
            lcn_addr = LcnAddr.from_string(addr_str)
            if device is None:
                device = {}

            device["address"] = lcn_addr
            devices[lcn_addr] = device

            # Log applied overrides
            flattened = flatten_with_values(
                {
                    key: value
                    for key, value in device.items()
                    if key in Device.model_fields and key != "address"
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

        finalize_device_components(homeassistant_config, device_config, self)

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
        """Customize the order of settings sources to include YAML file."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def finalize_device_components(
    homeassistant: HomeAssistantModuleDiscoveryConfig,
    device: DeviceConfig,
    config: AppConfig,
) -> None:
    """Finalize the components of a Home Assistant module discovery config."""
    homeassistant.address = device.address
    # update discovery components
    homeassistant.prepare_auto_components()
    homeassistant.update_components()

    # inject positioning_mode from device to cover components
    for cover in homeassistant.covers.values():
        motor = cover.target.name.lower()
        motor = "motor_outputs" if motor == "outputs" else motor

        motor_obj = getattr(device, motor, None)
        if motor_obj is not None:
            cover.positioning_mode = motor_obj.positioning_mode

    # inject mqtt base_topic into discovery components
    homeassistant.update_base_topic(config.mqtt.base_topic)


def finalize_config(config: AppConfig) -> None:
    """Finalize the configuration by injecting additional parameters."""
    for device in config.devices.values():
        if device.homeassistant is not None:
            finalize_device_components(device.homeassistant, device, config)


def load_config(
    config_path: str = "./data",
) -> AppConfig:
    """Load configuration from the specified YAML file and environment variables."""
    local_config_path = os.environ.get("LCN2MQTT__CONFIG_PATH", config_path)
    if os.environ.get("LCN2MQTT__RUNNING_IN_DOCKER", "false").lower() == "true":
        # if RUNNING_IN_DOCKER is set, use /lcn2mqtt/data as config path
        config_path = "/lcn2mqtt/data"
        _LOG.info("Running in Docker")
    else:
        config_path = local_config_path

    if not os.path.exists(config_path):
        _LOG.warning(
            "Local config path at %s does not exist",
            config_path,
        )
    else:
        _LOG.info("Using local config path: %s", local_config_path)

    yaml_file = os.path.join(config_path, "configuration.yaml")
    config = AppConfig(yaml_file=yaml_file)
    finalize_config(config)
    return config


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    config = load_config(
        os.path.expanduser("~/workspaces/lcn2mqtt/data/configuration.yaml")
    )
    # print(config.model_dump_json(indent=2))
    # print(config.mqtt.base_topic)
    # print(type(list(config.devices.values())[0].homeassistant))
    # for addr, device in config.devices.items():
    #     print(device)
    #     print(device.module_overrides)
    #     print(device.homeassistant)
