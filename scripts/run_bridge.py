#!/usr/bin/env python3
"""Run the WebSocket bridge as a standalone service.

The bridge relays NATS market messages to WebSocket clients (viewers).
When running separately from the season runner, the bridge operates
in relay-only mode without access to world state infrastructure.

Usage:
    python scripts/run_bridge.py
    python scripts/run_bridge.py --nats-url nats://nats:4222 --ws-port 9090
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.websocket_bridge.bridge import WebSocketBridge  # noqa: E402

logger = logging.getLogger("run_bridge")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the AI Street Market WebSocket bridge.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--nats-url",
        default="nats://localhost:4222",
        help="NATS server URL",
    )
    parser.add_argument(
        "--ws-host",
        default="0.0.0.0",
        help="WebSocket server bind host",
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=9090,
        help="WebSocket server port",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    """Main entry point — run the WebSocket bridge."""
    args = parse_args(argv)

    # Set up logging
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)
    logging.getLogger("nats").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    logger.info(
        "Starting WebSocket bridge: NATS=%s, WS=%s:%d",
        args.nats_url,
        args.ws_host,
        args.ws_port,
    )

    bridge = WebSocketBridge(
        nats_url=args.nats_url,
        ws_host=args.ws_host,
        ws_port=args.ws_port,
    )

    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await bridge.start()
    logger.info("WebSocket bridge running on ws://%s:%d", args.ws_host, args.ws_port)

    try:
        await shutdown_event.wait()
    finally:
        await bridge.stop()
        logger.info("WebSocket bridge stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
