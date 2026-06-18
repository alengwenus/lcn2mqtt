"""Helper functions for LCN2MQTT."""


def normalize_def_names(name: str) -> str:
    """Normalize LCN definition names."""
    if not isinstance(name, str):
        return name
    return name.lower().replace("variable", "var").replace("threshold", "thrs")
