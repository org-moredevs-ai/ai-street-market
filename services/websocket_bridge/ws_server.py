"""WebSocket server — manages browser connections and message fan-out.

Uses the `websockets` library for lightweight async WebSocket support.
Sends a STATE_SNAPSHOT to each new client on connect and broadcasts
filtered NATS messages to all connected clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets
from websockets.asyncio.server import Server, ServerConnection

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5.0  # seconds — slow clients get disconnected


class WebSocketServer:
    """Manages WebSocket connections from browser viewers.

    New clients receive a snapshot immediately on connect.
    Broadcast messages are fanned out to all connected clients with a
    per-client timeout to prevent slow clients from blocking NATS processing.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9090) -> None:
        self._host = host
        self._port = port
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._snapshot_provider: Callable[[], dict[str, Any]] | None = None

    @property
    def client_count(self) -> int:
        """Number of currently connected WebSocket clients."""
        return len(self._clients)

    def set_snapshot_provider(self, fn: Callable[[], dict[str, Any]]) -> None:
        """Set the callback that returns the current state snapshot."""
        self._snapshot_provider = fn

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self._handle_client,
            self._host,
            self._port,
        )
        logger.info("WebSocket server listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Close all connections and stop the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()
        logger.info("WebSocket server stopped")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Fan-out a JSON message to all connected clients.

        Each send has a SEND_TIMEOUT. Clients that can't receive in time
        are disconnected to prevent blocking NATS message processing.
        """
        if not self._clients:
            return

        data = json.dumps(message)
        stale: list[ServerConnection] = []

        for ws in list(self._clients):
            try:
                await asyncio.wait_for(ws.send(data), timeout=SEND_TIMEOUT)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed, OSError):
                stale.append(ws)

        for ws in stale:
            self._clients.discard(ws)
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_client(self, websocket: ServerConnection) -> None:
        """Handle a new WebSocket client connection."""
        self._clients.add(websocket)
        logger.info(
            "Client connected (%d total)",
            self.client_count,
        )

        # Send snapshot on connect
        if self._snapshot_provider is not None:
            try:
                snapshot = self._snapshot_provider()
                msg = json.dumps({"type": "snapshot", "data": snapshot})
                await asyncio.wait_for(websocket.send(msg), timeout=SEND_TIMEOUT)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed, OSError):
                self._clients.discard(websocket)
                return

        try:
            # Keep connection alive — we only send, clients don't need to send
            async for _ in websocket:
                pass  # Ignore any client messages
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info(
                "Client disconnected (%d remaining)",
                self.client_count,
            )
