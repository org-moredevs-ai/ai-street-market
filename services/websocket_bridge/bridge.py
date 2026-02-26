"""WebSocketBridgeService — subscribes to NATS topics and forwards filtered
messages to browser WebSocket clients.

Follows the TownCrier service pattern: connect to NATS, subscribe to
/market/>, /system/>, /world/>, classify each message, update aggregate
state, and broadcast to connected viewers.
"""

from __future__ import annotations

import logging

from streetmarket import Envelope, MarketBusClient, MessageType

from services.websocket_bridge.filter import should_forward, should_update_state
from services.websocket_bridge.state import BridgeState
from services.websocket_bridge.ws_server import WebSocketServer

logger = logging.getLogger(__name__)


class WebSocketBridgeService:
    """Bridges NATS messages to browser WebSocket clients.

    Subscribes to all market, system, and world topics. Each incoming
    message is classified, used to update aggregate state, and optionally
    broadcast to connected WebSocket clients.
    """

    AGENT_ID = "websocket_bridge"

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        ws_host: str = "0.0.0.0",
        ws_port: int = 9090,
    ) -> None:
        self._bus = MarketBusClient(nats_url)
        self._state = BridgeState()
        self._ws = WebSocketServer(host=ws_host, port=ws_port)
        self._ws.set_snapshot_provider(self._state.get_snapshot)

    @property
    def state(self) -> BridgeState:
        """Expose state for testing."""
        return self._state

    @property
    def ws_server(self) -> WebSocketServer:
        """Expose WS server for testing."""
        return self._ws

    async def start(self) -> None:
        """Connect to NATS, start WebSocket server, subscribe to topics."""
        await self._bus.connect()
        logger.info("Bridge connected to NATS")

        await self._ws.start()
        logger.info("Bridge WebSocket server started")

        await self._bus.subscribe("/market/>", self._on_message)
        await self._bus.subscribe("/system/>", self._on_message)
        await self._bus.subscribe("/world/>", self._on_message)
        logger.info("Bridge subscribed to market.>, system.>, world.>")

    async def stop(self) -> None:
        """Stop WebSocket server and close NATS connection."""
        await self._ws.stop()
        await self._bus.close()
        logger.info("Bridge stopped")

    async def _on_message(self, envelope: Envelope) -> None:
        """Classify, update state, and optionally broadcast."""
        msg_type = envelope.type
        payload = envelope.payload
        tick = envelope.tick

        # Update aggregate state
        if should_update_state(msg_type):
            self._update_state(msg_type, payload, tick, from_agent=envelope.from_agent)

        # Broadcast to WebSocket clients
        if should_forward(msg_type):
            serialized = envelope.model_dump(by_alias=True)
            self._state.recent_events.append(serialized)
            await self._ws.broadcast({
                "type": "event",
                "data": serialized,
            })

    def _update_state(self, msg_type: str, payload: dict, tick: int, from_agent: str = "") -> None:
        """Route message to the appropriate BridgeState handler."""
        if msg_type == MessageType.TICK:
            tick_number = payload.get("tick_number", 0)
            self._state.on_tick(tick_number)

        elif msg_type == MessageType.JOIN:
            self._state.on_join(payload, tick)

        elif msg_type == MessageType.ENERGY_UPDATE:
            self._state.on_energy_update(payload)

        elif msg_type == MessageType.SETTLEMENT:
            self._state.on_settlement(payload, tick)

        elif msg_type == MessageType.NARRATION:
            self._state.on_narration(payload)

        elif msg_type == MessageType.NATURE_EVENT:
            self._state.on_nature_event(payload)

        elif msg_type == MessageType.BANKRUPTCY:
            self._state.on_bankruptcy(payload)

        elif msg_type == MessageType.RENT_DUE:
            self._state.on_rent_due(payload)

        elif msg_type == MessageType.HEARTBEAT:
            self._state.on_heartbeat(payload, tick)

        elif msg_type == MessageType.CRAFT_COMPLETE:
            self._state.on_craft_complete(payload)

        elif msg_type == MessageType.AGENT_STATUS:
            self._state.on_agent_status(payload, tick)

        elif msg_type == MessageType.ITEM_SPOILED:
            self._state.on_item_spoiled(payload)

        elif msg_type == MessageType.ECONOMY_HALT:
            self._state.on_economy_halt(payload)

        elif msg_type in (MessageType.OFFER, MessageType.BID, MessageType.ACCEPT):
            self._state.on_trade_action(from_agent)
