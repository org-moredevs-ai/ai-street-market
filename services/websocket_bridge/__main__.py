"""Entry point: python -m services.websocket_bridge"""

import asyncio
import logging
import os
import signal

from services.websocket_bridge.bridge import WebSocketBridgeService


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    ws_host = os.environ.get("WS_BRIDGE_HOST", "0.0.0.0")
    ws_port = int(os.environ.get("WS_BRIDGE_PORT", "9090"))

    service = WebSocketBridgeService(
        nats_url=nats_url,
        ws_host=ws_host,
        ws_port=ws_port,
    )

    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await service.start()
    logging.getLogger(__name__).info("WebSocket Bridge is running. Press Ctrl+C to stop.")

    await stop_event.wait()
    await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
