"""WebSocket bridge — relays NATS market messages to browser WebSocket clients.

The bridge connects to NATS as a subscriber and runs a WebSocket server.
Browser clients connect to the WS server and receive:

1. **Live messages** from all public market topics (NL conversations)
2. **State snapshots** with current world state (agents, weather, season, rankings)

The viewer is read-only — clients cannot publish back to NATS.

Architecture:
    NATS (market.>) --subscribe--> Bridge --broadcast--> WebSocket Clients

Protocol (server → client):
    {"type": "message", "data": {envelope}}         — live NL message
    {"type": "state",   "data": {state snapshot}}    — world state snapshot
    {"type": "history", "data": [recent messages]}   — recent messages on connect

Usage:
    bridge = WebSocketBridge(
        nats_url="nats://localhost:4222",
        ws_host="0.0.0.0",
        ws_port=9090,
    )
    await bridge.start()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any

import websockets
from streetmarket.client.nats_client import MarketBusClient
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics
from streetmarket.ranking import RankingEngine
from streetmarket.registry import AgentRegistry
from streetmarket.season import SeasonManager
from streetmarket.world_state import WorldStateStore
from websockets.asyncio.server import Server, ServerConnection

logger = logging.getLogger(__name__)

# Maximum recent messages to buffer for new clients
MAX_HISTORY = 200

# How often to broadcast state snapshots (seconds)
STATE_BROADCAST_INTERVAL = 30.0


class WebSocketBridge:
    """Relay NATS market messages to WebSocket browser clients."""

    def __init__(
        self,
        *,
        nats_url: str = "nats://localhost:4222",
        ws_host: str = "0.0.0.0",
        ws_port: int = 9090,
        registry: AgentRegistry | None = None,
        world_state: WorldStateStore | None = None,
        season_manager: SeasonManager | None = None,
        ranking_engine: RankingEngine | None = None,
        state_interval: float = STATE_BROADCAST_INTERVAL,
    ) -> None:
        self._nats_url = nats_url
        self._ws_host = ws_host
        self._ws_port = ws_port
        self._state_interval = state_interval

        # World state components (optional — bridge works without them)
        self._registry = registry
        self._world_state = world_state
        self._season = season_manager
        self._ranking = ranking_engine

        # Internal state
        self._nats: MarketBusClient | None = None
        self._ws_server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY)
        self._current_tick = 0
        self._running = False

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def current_tick(self) -> int:
        return self._current_tick

    # -- Lifecycle --

    async def start(self) -> None:
        """Connect to NATS, start WebSocket server, begin relaying."""
        # Connect to NATS
        self._nats = MarketBusClient(self._nats_url)
        await self._nats.connect()

        # Subscribe to all public market topics + tick
        for topic in Topics.all_market_topics():
            await self._nats.subscribe(topic, self._on_nats_message)
        await self._nats.subscribe(Topics.TICK, self._on_tick)

        logger.info(
            "Bridge connected to NATS at %s, subscribed to %d topics",
            self._nats_url,
            len(Topics.all_market_topics()) + 1,
        )

        # Start WebSocket server
        self._ws_server = await websockets.serve(
            self._on_ws_connect,
            self._ws_host,
            self._ws_port,
        )
        self._running = True

        logger.info(
            "WebSocket bridge listening on ws://%s:%d",
            self._ws_host,
            self._ws_port,
        )

    async def stop(self) -> None:
        """Shut down the bridge."""
        self._running = False

        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
            self._ws_server = None

        if self._nats:
            await self._nats.close()
            self._nats = None

        self._clients.clear()
        logger.info("WebSocket bridge stopped")

    async def run(self) -> None:
        """Run the bridge until stopped (blocking)."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # -- NATS Handlers --

    async def _on_tick(self, envelope: Envelope) -> None:
        """Handle tick messages — update current tick."""
        self._current_tick = envelope.tick

    async def _on_nats_message(self, envelope: Envelope) -> None:
        """Handle incoming NATS messages — relay to all WS clients."""
        msg_data = _envelope_to_dict(envelope)
        self._history.append(msg_data)

        payload = json.dumps({"type": "message", "data": msg_data})
        await self._broadcast(payload)

    # -- WebSocket Handlers --

    async def _on_ws_connect(self, ws: ServerConnection) -> None:
        """Handle new WebSocket client connection."""
        self._clients.add(ws)
        client_addr = _ws_addr(ws)
        logger.info(
            "Viewer connected: %s (total: %d)",
            client_addr,
            len(self._clients),
        )

        try:
            # Send recent message history
            if self._history:
                history_payload = json.dumps(
                    {
                        "type": "history",
                        "data": list(self._history),
                    }
                )
                await ws.send(history_payload)

            # Send current state snapshot
            state = self._build_state_snapshot()
            if state:
                await ws.send(json.dumps({"type": "state", "data": state}))

            # Keep connection alive — read (and discard) client messages
            async for _ in ws:
                pass  # Viewer is read-only; ignore client messages

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            logger.info(
                "Viewer disconnected: %s (total: %d)",
                client_addr,
                len(self._clients),
            )

    # -- Broadcasting --

    async def _broadcast(self, payload: str) -> None:
        """Send a message to all connected WebSocket clients."""
        if not self._clients:
            return

        dead: list[ServerConnection] = []
        for ws in self._clients:
            try:
                await ws.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.append(ws)
            except Exception:
                logger.debug("Failed to send to client, removing")
                dead.append(ws)

        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_state(self) -> None:
        """Broadcast a state snapshot to all connected clients."""
        state = self._build_state_snapshot()
        if state:
            payload = json.dumps({"type": "state", "data": state})
            await self._broadcast(payload)

    # -- State Snapshots --

    def _build_state_snapshot(self) -> dict[str, Any]:
        """Build a world state snapshot for viewers.

        Accesses internal store dicts directly (sync) to avoid async
        in the snapshot builder. Safe because bridge and stores share the same process.
        """
        snapshot: dict[str, Any] = {
            "tick": self._current_tick,
            "timestamp": time.time(),
        }

        if self._registry:
            agents = []
            for record in self._registry._agents.values():
                agents.append(
                    {
                        "agent_id": record.id,
                        "display_name": record.display_name,
                        "state": record.state.value,
                        "description": record.profile.description,
                        "joined_tick": record.joined_tick,
                    }
                )
            snapshot["agents"] = agents

        if self._world_state:
            weather = self._world_state._weather
            weather_dict: dict[str, Any] = {
                "condition": weather.condition,
                "temperature": weather.temperature,
                "wind": weather.wind,
            }
            if weather.temperature_celsius is not None:
                weather_dict["temperature_celsius"] = weather.temperature_celsius
                weather_dict["temperature_fahrenheit"] = round(
                    weather.temperature_celsius * 9 / 5 + 32
                )
            snapshot["weather"] = weather_dict

            fields = []
            for f in self._world_state._fields.values():
                fields.append(
                    {
                        "field_id": f.id,
                        "crop": f.crop,
                        "status": f.status.value,
                        "owner": f.owner,
                    }
                )
            snapshot["fields"] = fields

            buildings = []
            for b in self._world_state._buildings.values():
                buildings.append(
                    {
                        "building_id": b.id,
                        "building_type": b.type,
                        "owner": b.owner,
                    }
                )
            snapshot["buildings"] = buildings

        if self._season:
            snapshot["season"] = {
                "name": self._season.config.name,
                "phase": self._season.phase.value,
                "progress": self._season.progress_percent,
            }

        if self._ranking and self._ranking._season_history:
            # Get latest season rankings
            latest_season = max(self._ranking._season_history.keys())
            entries = self._ranking._season_history[latest_season]
            snapshot["rankings"] = [
                {
                    "rank": e.rank,
                    "agent_id": e.agent_id,
                    "owner": e.owner,
                    "total_score": e.total_score,
                    "scores": e.scores,
                    "state": e.state,
                }
                for e in entries
            ]

            overall = self._ranking.get_overall_rankings()
            if overall:
                snapshot["overall_rankings"] = [
                    {
                        "rank": o.rank,
                        "owner": o.owner,
                        "total_score": o.total_score,
                        "seasons_played": o.seasons_played,
                        "wins": o.wins,
                    }
                    for o in overall
                ]

        return snapshot


# -- Helpers --


def _envelope_to_dict(envelope: Envelope) -> dict[str, Any]:
    """Convert an Envelope to a viewer-friendly dict."""
    return {
        "id": envelope.id,
        "from": envelope.from_agent,
        "topic": envelope.topic,
        "timestamp": envelope.timestamp,
        "tick": envelope.tick,
        "message": envelope.message,
    }


def _ws_addr(ws: ServerConnection) -> str:
    """Get a display-friendly address for a WebSocket connection."""
    try:
        remote = ws.remote_address
        if remote:
            return f"{remote[0]}:{remote[1]}"
    except Exception:
        pass
    return "unknown"
