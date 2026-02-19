"""Entry point: python -m services.banker"""

import asyncio
import logging
import signal

from services.banker.banker import BankerAgent


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    banker = BankerAgent()
    loop = asyncio.get_running_loop()

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await banker.start()
    logging.getLogger(__name__).info("Banker is running. Press Ctrl+C to stop.")

    await stop_event.wait()
    await banker.stop()


if __name__ == "__main__":
    asyncio.run(main())
