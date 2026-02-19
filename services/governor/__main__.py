"""Entry point: python -m services.governor"""

import asyncio
import logging
import signal

from services.governor.governor import GovernorAgent


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    governor = GovernorAgent()
    loop = asyncio.get_running_loop()

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await governor.start()
    logging.getLogger(__name__).info("Governor is running. Press Ctrl+C to stop.")

    await stop_event.wait()
    await governor.stop()


if __name__ == "__main__":
    asyncio.run(main())
