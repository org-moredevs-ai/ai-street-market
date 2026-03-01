#!/usr/bin/env python3
"""Run the Agent Runner — loads and runs managed agents from MongoDB.

Usage:
    python scripts/run_agent_runner.py
    python scripts/run_agent_runner.py --nats-url nats://nats:4222
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

from services.agent_runner.runner import AgentRunner  # noqa: E402

logger = logging.getLogger("run_agent_runner")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Agent Runner service.")
    parser.add_argument(
        "--nats-url",
        default=os.environ.get("NATS_URL", "nats://localhost:4222"),
        help="NATS server URL",
    )
    parser.add_argument(
        "--runner-id",
        default=os.environ.get("RUNNER_ID"),
        help="Unique runner ID (auto-generated if not set)",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)

    logger.info("Agent Runner starting...")
    logger.info("NATS: %s", args.nats_url)
    logger.info("MongoDB: %s", os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))

    # Connect to NATS
    nc = await nats_lib.connect(args.nats_url)
    logger.info("NATS connected")

    # Create runner
    runner = AgentRunner(
        nc,
        runner_id=args.runner_id,
        nats_url=args.nats_url,
    )
    await runner.start()

    # Shutdown handling
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Agent Runner %s ready — managing agents...", runner.runner_id)

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down...")
        await runner.stop()
        await nc.close()
        from streetmarket.db.connection import close_database

        await close_database()
        logger.info("Agent Runner stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
