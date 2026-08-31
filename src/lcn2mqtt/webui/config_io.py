"""YAML configuration I/O helpers for the WebUI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def get_config_path() -> Path:
    """Resolve config file path using the same env-var logic as load_config."""
    if os.environ.get("LCN2MQTT__RUNNING_IN_DOCKER", "false").lower() == "true":
        base = Path("/lcn2mqtt/data")
    else:
        base = Path(os.environ.get("LCN2MQTT__CONFIG_PATH", "./data"))
    return base / "configuration.yaml"


def read_yaml() -> dict[str, Any]:
    """Load the YAML config as a plain dict."""
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError:
        return {}


def get_env_overrides() -> dict[str, str]:
    """Return dot-path -> value for fields set by env variables or .env file."""
    _PREFIX = "LCN2MQTT__"
    overrides: dict[str, str] = {}

    def _register(raw_key: str, value: str) -> None:
        tail = raw_key[len(_PREFIX) :]
        overrides[".".join(tail.lower().split("__"))] = value

    env_file = Path(".env")
    if env_file.exists():
        try:
            with env_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        if key.upper().startswith(_PREFIX):
                            _register(key.upper(), val.strip())
        except OSError:
            pass

    # env vars take precedence over .env
    for key in os.environ:
        if key.upper().startswith(_PREFIX):
            _register(key.upper(), os.environ[key])

    return overrides


def write_yaml(data: dict[str, Any]) -> None:
    """Write a dict to the YAML config file."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def write_keys(updates: dict[str, Any]) -> None:
    """Update a set of top-level keys and write the full config back."""
    cfg = read_yaml()
    for key, value in updates.items():
        cleaned = _strip_nones(value) if isinstance(value, dict) else value
        if cleaned is None or cleaned == {}:
            cfg.pop(key, None)
        else:
            cfg[key] = cleaned
    write_yaml(cfg)


def _strip_nones(obj: Any) -> Any:
    """Recursively remove None values and empty dicts."""
    if isinstance(obj, dict):
        result = {k: _strip_nones(v) for k, v in obj.items() if v is not None}
        return {k: v for k, v in result.items() if v != {}}
    return obj
