"""Entry point: python -m __main__ (or python __main__.py)"""

import asyncio
import logging
import os
import signal

from agent import MyAgent


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    agent = MyAgent(nats_url)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await agent.start()
    logging.info("Agent running — press Ctrl+C to stop")

    await stop.wait()
    await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
