"""Entry point: ``python -m lcn2mqtt``."""

from __future__ import annotations

import asyncio
import logging
import signal

from .bridge import Bridge
from .config import load_config


def _setup_logging(level: str) -> logging.Logger:
    """Configure logging with the specified log level."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    return root


async def _amain() -> None:
    """Main async entry point for the bridge."""
    log = _setup_logging("INFO")
    log.info("Starting lcn2mqtt bridge")
    config = load_config()
    log.setLevel(config.log_level)

    bridge = Bridge(config)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    run_task = asyncio.create_task(bridge.run())
    stop_task = asyncio.create_task(stop.wait())

    done, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc is not None and not isinstance(exc, asyncio.CancelledError):
            log.error("Bridge stopped with error: %s", exc)
            raise exc

    log.info("Shutting down")


def main() -> None:
    """Main entry point for the application."""
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
