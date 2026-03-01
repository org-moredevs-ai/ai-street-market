#!/usr/bin/env python3
"""Run the Agent Manager — NATS request-reply service for managed agent CRUD.

Usage:
    python scripts/run_agent_manager.py
    python scripts/run_agent_manager.py --nats-url nats://nats:4222
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import nats as nats_lib  # noqa: E402

from services.agent_manager.manager import AgentManager  # noqa: E402

logger = logging.getLogger("run_agent_manager")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Agent Manager service.")
    parser.add_argument(
        "--nats-url",
        default=os.environ.get("NATS_URL", "nats://localhost:4222"),
        help="NATS server URL",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)

    logger.info("Agent Manager starting...")
    logger.info("NATS: %s", args.nats_url)
    logger.info("MongoDB: %s", os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))

    # Connect to NATS
    nc = await nats_lib.connect(args.nats_url)
    logger.info("NATS connected")

    # Start manager
    manager = AgentManager(nc)
    await manager.start()

    # Shutdown handling
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Agent Manager ready — waiting for requests...")

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down...")
        await nc.close()
        from streetmarket.db.connection import close_database

        await close_database()
        logger.info("Agent Manager stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
