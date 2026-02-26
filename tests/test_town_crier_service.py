"""Tests for TownCrierService — message handling and narration publishing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from streetmarket import (
    Envelope,
    MessageType,
    Topics,
)

from services.town_crier.narrator import NarrationResult
from services.town_crier.state import NARRATION_INTERVAL
from services.town_crier.town_crier import TownCrierService

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


def _make_service() -> TownCrierService:
    """Create a TownCrierService with mocked bus and narrator."""
    service = TownCrierService.__new__(TownCrierService)
    service._bus = AsyncMock()
    service._state = __import__(
        "services.town_crier.state", fromlist=["TownCrierState"]
    ).TownCrierState()
    service._narrator = MagicMock()
    service._narrator.generate_narration = AsyncMock(
        return_value=NarrationResult(
            headline="Test narration",
            body="Test body",
            predictions=None,
            drama_level=1,
        )
    )
    service._economy_halted = False
    return service


# ── Service identity ─────────────────────────────────────────────────────────


class TestServiceIdentity:
    def test_agent_id(self) -> None:
        assert TownCrierService.AGENT_ID == "town_crier"


# ── System message handling ──────────────────────────────────────────────────


class TestSystemMessages:
    async def test_tick_advances_state(self) -> None:
        svc = _make_service()
        env = _make_envelope(MessageType.TICK, {"tick_number": 3}, topic=Topics.TICK)
        await svc._on_system_message(env)
        assert svc.state.current_tick == 3

    async def test_tick_triggers_narration_at_interval(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.TICK,
            {"tick_number": NARRATION_INTERVAL},
            topic=Topics.TICK,
        )
        await svc._on_system_message(env)
        svc._narrator.generate_narration.assert_called_once()
        svc._bus.publish.assert_called_once()

    async def test_tick_does_not_narrate_between_intervals(self) -> None:
        svc = _make_service()
        env = _make_envelope(MessageType.TICK, {"tick_number": 3}, topic=Topics.TICK)
        await svc._on_system_message(env)
        svc._narrator.generate_narration.assert_not_called()
        svc._bus.publish.assert_not_called()

    async def test_energy_update_records_levels(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.ENERGY_UPDATE,
            {"energy_levels": {"farmer": 80.0, "chef": 60.0}, "tick": 1},
        )
        await svc._on_system_message(env)
        assert svc.state.energy_levels == {"farmer": 80.0, "chef": 60.0}


# ── Market message handling ──────────────────────────────────────────────────


class TestMarketMessages:
    async def test_settlement_recorded(self) -> None:
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
        )
        await svc._on_market_message(env)
        assert len(svc.state.settlements) == 1
        assert svc.state.settlements[0].buyer == "chef"

    async def test_settlement_records_activity_for_both(self) -> None:
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
        )
        await svc._on_market_message(env)
        assert svc.state.activity_counts.get("chef") == 1
        assert svc.state.activity_counts.get("farmer") == 1

    async def test_bankruptcy_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.BANKRUPTCY,
            {"agent_id": "farmer", "reason": "broke"},
            from_agent="banker",
        )
        await svc._on_market_message(env)
        assert svc.state.bankruptcies == ["farmer"]

    async def test_rent_due_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.RENT_DUE,
            {"agent_id": "farmer", "amount": 2.0, "wallet_after": 48.0},
            from_agent="banker",
        )
        await svc._on_market_message(env)
        assert len(svc.state.rent_payments) == 1

    async def test_join_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "mason", "name": "Mason", "description": "Stone worker"},
            from_agent="mason",
        )
        await svc._on_market_message(env)
        assert svc.state.joins == ["mason"]

    async def test_craft_complete_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "chef"},
            from_agent="chef",
        )
        await svc._on_market_message(env)
        assert len(svc.state.crafts) == 1
        assert svc.state.crafts[0].output == "soup"

    async def test_offer_records_activity(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
            from_agent="farmer",
        )
        await svc._on_market_message(env)
        assert svc.state.activity_counts.get("farmer") == 1

    async def test_bid_records_activity(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 5, "max_price_per_unit": 3.0},
            from_agent="chef",
        )
        await svc._on_market_message(env)
        assert svc.state.activity_counts.get("chef") == 1

    async def test_skips_own_messages(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
            from_agent="town_crier",
        )
        await svc._on_market_message(env)
        assert len(svc.state.activity_counts) == 0


# ── World message handling ───────────────────────────────────────────────────


class TestWorldMessages:
    async def test_nature_event_recorded(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.NATURE_EVENT,
            {
                "event_id": "ev1",
                "title": "Drought",
                "description": "Water dries up",
                "effects": {"potato": 0.5},
                "duration_ticks": 5,
                "remaining_ticks": 5,
            },
            from_agent="world",
            topic=Topics.NATURE,
        )
        await svc._on_world_message(env)
        assert len(svc.state.nature_events) == 1
        assert svc.state.nature_events[0]["title"] == "Drought"

    async def test_non_nature_event_ignored(self) -> None:
        svc = _make_service()
        env = _make_envelope(
            MessageType.SPAWN,
            {"spawn_id": "s1", "tick": 1, "items": {"potato": 10}},
            from_agent="world",
            topic=Topics.NATURE,
        )
        await svc._on_world_message(env)
        assert len(svc.state.nature_events) == 0


# ── Narration publishing ────────────────────────────────────────────────────


class TestNarrationPublishing:
    async def test_narration_envelope_published(self) -> None:
        svc = _make_service()
        # Advance to narration tick
        svc.state.advance_tick(NARRATION_INTERVAL)
        await svc._maybe_narrate(NARRATION_INTERVAL)

        svc._bus.publish.assert_called_once()
        call_args = svc._bus.publish.call_args[0]
        assert call_args[0] == Topics.SQUARE
        env = call_args[1]
        assert env.type == MessageType.NARRATION
        assert env.from_agent == "town_crier"
        assert env.topic == Topics.SQUARE

    async def test_narration_resets_window(self) -> None:
        svc = _make_service()
        svc.state.record_settlement("b", "s", "potato", 1, 5.0)
        svc.state.advance_tick(NARRATION_INTERVAL)
        await svc._maybe_narrate(NARRATION_INTERVAL)
        # Window should be reset
        assert len(svc.state.settlements) == 0
        assert svc.state.window_start_tick == NARRATION_INTERVAL

    async def test_narration_payload_has_weather(self) -> None:
        svc = _make_service()
        svc.state.advance_tick(NARRATION_INTERVAL)
        await svc._maybe_narrate(NARRATION_INTERVAL)

        env = svc._bus.publish.call_args[0][1]
        assert "weather" in env.payload

    async def test_no_narration_at_wrong_tick(self) -> None:
        svc = _make_service()
        await svc._maybe_narrate(3)
        svc._bus.publish.assert_not_called()

    async def test_multiple_narrations(self) -> None:
        svc = _make_service()
        for tick in range(NARRATION_INTERVAL, NARRATION_INTERVAL * 3 + 1, NARRATION_INTERVAL):
            svc.state.advance_tick(tick)
            await svc._maybe_narrate(tick)
        assert svc._bus.publish.call_count == 3
