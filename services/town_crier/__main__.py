"""Entry point: python -m services.town_crier"""

import asyncio
import logging
import signal

from services.town_crier.town_crier import TownCrierService


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    service = TownCrierService()
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await service.start()
    logging.getLogger(__name__).info("Town Crier is running. Press Ctrl+C to stop.")

    await stop_event.wait()
    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
