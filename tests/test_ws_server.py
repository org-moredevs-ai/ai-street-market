"""Tests for the WebSocket server — connection management and broadcasting."""

from __future__ import annotations

import asyncio
import json

import websockets

from services.websocket_bridge.ws_server import WebSocketServer


def _free_port() -> int:
    """Find a free port on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Initialization ───────────────────────────────────────────────────────────


class TestInit:
    def test_defaults(self) -> None:
        server = WebSocketServer()
        assert server.client_count == 0

    def test_custom_host_port(self) -> None:
        server = WebSocketServer(host="127.0.0.1", port=9999)
        assert server._host == "127.0.0.1"
        assert server._port == 9999


# ── Start / Stop ─────────────────────────────────────────────────────────────


class TestStartStop:
    async def test_start_and_stop(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        await server.start()
        assert server._server is not None
        await server.stop()
        assert server._server is None

    async def test_stop_without_start(self) -> None:
        server = WebSocketServer()
        await server.stop()  # Should not raise


# ── Client connections ───────────────────────────────────────────────────────


class TestClientConnections:
    async def test_client_connects_and_counted(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}"):
                await asyncio.sleep(0.05)
                assert server.client_count == 1
        finally:
            await server.stop()

    async def test_client_disconnect_decrements_count(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        await server.start()
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}")
            await asyncio.sleep(0.05)
            assert server.client_count == 1
            await ws.close()
            await asyncio.sleep(0.05)
            assert server.client_count == 0
        finally:
            await server.stop()

    async def test_multiple_clients(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}"):
                async with websockets.connect(f"ws://127.0.0.1:{port}"):
                    await asyncio.sleep(0.05)
                    assert server.client_count == 2
        finally:
            await server.stop()


# ── Snapshot on connect ──────────────────────────────────────────────────────


class TestSnapshotOnConnect:
    async def test_sends_snapshot_on_connect(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        server.set_snapshot_provider(lambda: {"current_tick": 42})
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                assert data["type"] == "snapshot"
                assert data["data"]["current_tick"] == 42
        finally:
            await server.stop()

    async def test_no_snapshot_without_provider(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        # No snapshot_provider set
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                # Should not receive any message
                with __import__("pytest").raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=0.2)
        finally:
            await server.stop()


# ── Broadcast ────────────────────────────────────────────────────────────────


class TestBroadcast:
    async def test_broadcast_to_all_clients(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws1:
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws2:
                    await asyncio.sleep(0.05)
                    await server.broadcast({"type": "event", "data": {"test": True}})

                    msg1 = await asyncio.wait_for(ws1.recv(), timeout=2.0)
                    msg2 = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                    assert json.loads(msg1)["data"]["test"] is True
                    assert json.loads(msg2)["data"]["test"] is True
        finally:
            await server.stop()

    async def test_broadcast_no_clients_is_noop(self) -> None:
        server = WebSocketServer()
        # Should not raise
        await server.broadcast({"type": "event", "data": {}})

    async def test_broadcast_snapshot_then_event(self) -> None:
        port = _free_port()
        server = WebSocketServer(host="127.0.0.1", port=port)
        server.set_snapshot_provider(lambda: {"tick": 1})
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                # First message: snapshot
                msg1 = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert json.loads(msg1)["type"] == "snapshot"

                # Second message: broadcast event
                await server.broadcast({"type": "event", "data": {"tick": 2}})
                msg2 = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert json.loads(msg2)["type"] == "event"
        finally:
            await server.stop()
