"""Entry point: ``python -m lcn2mqtt``."""

from __future__ import annotations

import logging

from nicegui import app, ui

from .models.config import load_config
from .webui.app import setup_ui
from .webui.manager import BridgeManager

_LOG = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        root.addHandler(handler)


def main() -> None:
    """Start the bridge and NiceGUI WebUI."""
    config = load_config()
    _setup_logging(config.log_level)
    _LOG.info("Starting lcn2mqtt")

    manager = BridgeManager(config)

    app.on_startup(manager.start)
    app.on_shutdown(manager.stop)

    setup_ui(manager)

    ui.run(
        host=config.webui.host,
        port=config.webui.port,
        title="lcn2mqtt",
        favicon="🌉",
        reload=False,
        show=False,
    )


if __name__ == "__main__":
    main()
