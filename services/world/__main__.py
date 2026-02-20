"""Entry point: python -m services.world"""

import asyncio
import logging
import signal

from services.world.world import WorldEngine


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    engine = WorldEngine()
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await engine.start()
    logging.getLogger(__name__).info("World Engine is running. Press Ctrl+C to stop.")

    await stop_event.wait()
    await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
