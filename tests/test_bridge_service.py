"""Tests for WebSocketBridgeService — message handling and state updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from streetmarket import Envelope, MessageType, Topics

from services.websocket_bridge.bridge import WebSocketBridgeService
from services.websocket_bridge.state import BridgeState

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_envelope(
    msg_type: str,
    payload: dict,
    from_agent: str = "test_agent",
    topic: str = Topics.SQUARE,
    tick: int = 1,
) -> Envelope:
    """Create a minimal Envelope for testing."""
    return Envelope(
        id="test-id",
        from_agent=from_agent,
        topic=topic,
        timestamp=1000.0,
        tick=tick,
        type=msg_type,
        payload=payload,
    )


def _make_service() -> WebSocketBridgeService:
    """Create a WebSocketBridgeService with mocked bus and WS server."""
    service = WebSocketBridgeService.__new__(WebSocketBridgeService)
    service._bus = AsyncMock()
    service._state = BridgeState()
    service._ws = MagicMock()
    service._ws.broadcast = AsyncMock()
    service._ws.set_snapshot_provider = MagicMock()
    return service


# ── Service identity ─────────────────────────────────────────────────────────


class TestServiceIdentity:
    def test_agent_id(self) -> None:
        assert WebSocketBridgeService.AGENT_ID == "websocket_bridge"


# ── Properties ───────────────────────────────────────────────────────────────


class TestProperties:
    def test_state_property(self) -> None:
        svc = _make_service()
        assert isinstance(svc.state, BridgeState)

    def test_ws_server_property(self) -> None:
        svc = _make_service()
        assert svc.ws_server is svc._ws


# ── Tick handling ────────────────────────────────────────────────────────────


class TestTickHandling:
    async def test_tick_updates_state(self) -> None:
        svc = _make_service()
        env = _make_envelope(MessageType.TICK, {"tick_number": 42}, topic=Topics.TICK)
        await svc._on_message(env)
        assert svc.state.current_tick == 42

    async def test_tick_is_broadcast(self) -> None:
        svc = _make_service()
        env = _make_envelope(MessageType.TICK, {"tick_number": 1}, topic=Topics.TICK)
        await svc._on_message(env)
        svc._ws.broadcast.assert_called_once()
        call_data = svc._ws.broadcast.call_args[0][0]
        assert call_data["type"] == "event"


# ── Join handling ────────────────────────────────────────────────────────────


class TestJoinHandling:
    async def test_join_registers_agent(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "farmer", "name": "Farmer", "description": "Grows food"},
            from_agent="farmer",
            tick=5,
        )
        await svc._on_message(env)
        assert "farmer" in svc.state.active_agents
        assert svc.state.active_agents["farmer"].name == "Farmer"

    async def test_join_is_broadcast(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "farmer", "name": "Farmer", "description": ""},
            from_agent="farmer",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_called_once()


# ── Energy update ────────────────────────────────────────────────────────────


class TestEnergyUpdate:
    async def test_energy_update_records_levels(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.ENERGY_UPDATE,
            {"energy_levels": {"farmer": 80.0, "chef": 60.0}, "tick": 1},
        )
        await svc._on_message(env)
        assert svc.state.energy_levels == {"farmer": 80.0, "chef": 60.0}


# ── Settlement handling ──────────────────────────────────────────────────────


class TestSettlementHandling:
    async def test_settlement_updates_prices(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.SETTLEMENT,
            {
                "reference_msg_id": "ref1",
                "buyer": "chef",
                "seller": "farmer",
                "item": "potato",
                "quantity": 5,
                "total_price": 10.0,
                "status": "completed",
            },
            from_agent="banker",
            tick=10,
        )
        await svc._on_message(env)
        assert "potato" in svc.state.recent_prices
        assert len(svc.state.recent_prices["potato"]) == 1

    async def test_settlement_is_broadcast(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.SETTLEMENT,
            {
                "reference_msg_id": "ref1",
                "buyer": "chef",
                "seller": "farmer",
                "item": "potato",
                "quantity": 5,
                "total_price": 10.0,
            },
            from_agent="banker",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_called_once()


# ── Narration handling ───────────────────────────────────────────────────────


class TestNarrationHandling:
    async def test_narration_updates_state(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.NARRATION,
            {"headline": "Boom!", "body": "Markets surge", "weather": "booming"},
            from_agent="town_crier",
        )
        await svc._on_message(env)
        assert svc.state.latest_narration is not None
        assert svc.state.market_weather == "booming"


# ── Bankruptcy handling ──────────────────────────────────────────────────────


class TestBankruptcyHandling:
    async def test_bankruptcy_marks_agent(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.BANKRUPTCY,
            {"agent_id": "farmer", "reason": "broke"},
            from_agent="banker",
        )
        await svc._on_message(env)
        assert "farmer" in svc.state.bankrupt_agents


# ── Nature event handling ────────────────────────────────────────────────────


class TestNatureEventHandling:
    async def test_nature_event_tracked(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.NATURE_EVENT,
            {"event_id": "ev1", "title": "Drought", "description": "Dry", "effects": {}},
            from_agent="world",
            topic=Topics.NATURE,
        )
        await svc._on_message(env)
        assert len(svc.state.active_nature_events) == 1


# ── Rent due handling ────────────────────────────────────────────────────────


class TestRentDueHandling:
    async def test_rent_due_updates_wallet(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.RENT_DUE,
            {"agent_id": "chef", "amount": 2.0, "wallet_after": 48.0},
            from_agent="banker",
        )
        await svc._on_message(env)
        assert svc.state.agent_wallets["chef"] == 48.0


# ── Heartbeat handling (state only, no broadcast) ────────────────────────────


class TestHeartbeatHandling:
    async def test_heartbeat_updates_last_seen(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.HEARTBEAT,
            {"agent_id": "farmer", "wallet": 100.0, "inventory_count": 5},
            from_agent="farmer",
            tick=15,
        )
        await svc._on_message(env)
        assert svc.state.agent_last_seen["farmer"] == 15

    async def test_heartbeat_not_broadcast(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.HEARTBEAT,
            {"agent_id": "farmer", "wallet": 100.0, "inventory_count": 5},
            from_agent="farmer",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_not_called()


# ── Craft complete handling ──────────────────────────────────────────────────


class TestCraftCompleteHandling:
    async def test_craft_complete_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "chef"},
            from_agent="chef",
        )
        await svc._on_message(env)
        assert len(svc.state.recent_crafts) == 1


# ── Ignored messages ─────────────────────────────────────────────────────────


class TestIgnoredMessages:
    async def test_gather_ignored(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.GATHER,
            {"spawn_id": "s1", "item": "potato", "quantity": 5},
            from_agent="farmer",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_not_called()

    async def test_consume_ignored(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="farmer",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_not_called()

    async def test_counter_ignored(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.COUNTER,
            {"reference_msg_id": "r1", "proposed_price": 5.0, "quantity": 1},
            from_agent="chef",
        )
        await svc._on_message(env)
        svc._ws.broadcast.assert_not_called()


# ── Broadcast format ─────────────────────────────────────────────────────────


class TestBroadcastFormat:
    async def test_broadcast_uses_event_wrapper(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.SETTLEMENT,
            {
                "reference_msg_id": "ref1",
                "buyer": "chef",
                "seller": "farmer",
                "item": "potato",
                "quantity": 5,
                "total_price": 10.0,
            },
            from_agent="banker",
        )
        await svc._on_message(env)
        call_data = svc._ws.broadcast.call_args[0][0]
        assert call_data["type"] == "event"
        assert "data" in call_data
        # Envelope serialized with alias ("from" not "from_agent")
        assert "from" in call_data["data"]

    async def test_broadcast_envelope_has_message_type(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "farmer", "name": "Farmer", "description": ""},
            from_agent="farmer",
        )
        await svc._on_message(env)
        call_data = svc._ws.broadcast.call_args[0][0]
        assert call_data["data"]["type"] == "join"
