"""Entry point: python -m agents.builder"""

import asyncio
import logging
import signal

from agents.builder.agent import BuilderAgent


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    agent = BuilderAgent()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await agent.start()
    logging.info("Builder agent running — press Ctrl+C to stop")

    await stop.wait()
    await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
