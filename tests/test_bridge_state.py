"""Tests for BridgeState — aggregate state for WebSocket snapshots."""

from __future__ import annotations

from services.websocket_bridge.state import (
    CRAFT_HISTORY_LIMIT,
    DERIVED_PRICE_WINDOW,
    PRICE_HISTORY_LIMIT,
    AgentInfo,
    BridgeState,
    PriceRecord,
)

# ── Helper dataclasses ───────────────────────────────────────────────────────


class TestAgentInfo:
    def test_fields(self) -> None:
        info = AgentInfo(agent_id="farmer", name="Farmer", description="Grows food", joined_tick=1)
        assert info.agent_id == "farmer"
        assert info.name == "Farmer"
        assert info.description == "Grows food"
        assert info.joined_tick == 1


class TestPriceRecord:
    def test_fields(self) -> None:
        rec = PriceRecord(
            item="potato", price_per_unit=2.0, quantity=5, tick=10, buyer="chef", seller="farmer"
        )
        assert rec.item == "potato"
        assert rec.price_per_unit == 2.0
        assert rec.quantity == 5
        assert rec.tick == 10
        assert rec.buyer == "chef"
        assert rec.seller == "farmer"


# ── Initial state ────────────────────────────────────────────────────────────


class TestInitialState:
    def test_defaults(self) -> None:
        state = BridgeState()
        assert state.current_tick == 0
        assert state.active_agents == {}
        assert state.energy_levels == {}
        assert state.agent_wallets == {}
        assert state.recent_prices == {}
        assert state.active_nature_events == []
        assert state.market_weather == "stable"
        assert state.latest_narration is None
        assert state.bankrupt_agents == set()
        assert state.agent_last_seen == {}
        assert len(state.recent_crafts) == 0


# ── on_tick ──────────────────────────────────────────────────────────────────


class TestOnTick:
    def test_updates_current_tick(self) -> None:
        state = BridgeState()
        state.on_tick(42)
        assert state.current_tick == 42

    def test_overwrites_previous_tick(self) -> None:
        state = BridgeState()
        state.on_tick(10)
        state.on_tick(20)
        assert state.current_tick == 20


# ── on_join ──────────────────────────────────────────────────────────────────


class TestOnJoin:
    def test_registers_agent(self) -> None:
        state = BridgeState()
        state.on_join(
            {"agent_id": "farmer", "name": "Farmer", "description": "Grows food"}, tick=5
        )
        assert "farmer" in state.active_agents
        info = state.active_agents["farmer"]
        assert info.name == "Farmer"
        assert info.description == "Grows food"
        assert info.joined_tick == 5

    def test_updates_last_seen(self) -> None:
        state = BridgeState()
        state.on_join({"agent_id": "chef", "name": "Chef", "description": ""}, tick=3)
        assert state.agent_last_seen["chef"] == 3

    def test_multiple_agents(self) -> None:
        state = BridgeState()
        state.on_join({"agent_id": "a", "name": "A", "description": ""}, tick=1)
        state.on_join({"agent_id": "b", "name": "B", "description": ""}, tick=2)
        assert len(state.active_agents) == 2

    def test_defaults_name_to_agent_id(self) -> None:
        state = BridgeState()
        state.on_join({"agent_id": "x"}, tick=1)
        assert state.active_agents["x"].name == "x"


# ── on_energy_update ─────────────────────────────────────────────────────────


class TestOnEnergyUpdate:
    def test_overwrites_energy(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 80.0, "chef": 60.0}})
        assert state.energy_levels == {"farmer": 80.0, "chef": 60.0}

    def test_replaces_previous(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 80.0}})
        state.on_energy_update({"energy_levels": {"chef": 50.0}})
        assert state.energy_levels == {"chef": 50.0}
        assert "farmer" not in state.energy_levels


# ── on_settlement ────────────────────────────────────────────────────────────


class TestOnSettlement:
    def test_records_price(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "potato", "quantity": 5, "total_price": 10.0,
             "buyer": "chef", "seller": "farmer"},
            tick=10,
        )
        assert "potato" in state.recent_prices
        assert len(state.recent_prices["potato"]) == 1
        rec = state.recent_prices["potato"][0]
        assert rec.price_per_unit == 2.0
        assert rec.buyer == "chef"

    def test_multiple_items(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "potato", "quantity": 1, "total_price": 2.0, "buyer": "a", "seller": "b"},
            tick=1,
        )
        state.on_settlement(
            {"item": "onion", "quantity": 1, "total_price": 3.0, "buyer": "a", "seller": "b"},
            tick=2,
        )
        assert len(state.recent_prices) == 2

    def test_ring_buffer_limit(self) -> None:
        state = BridgeState()
        for i in range(PRICE_HISTORY_LIMIT + 5):
            state.on_settlement(
                {"item": "wood", "quantity": 1, "total_price": float(i),
                 "buyer": "a", "seller": "b"},
                tick=i,
            )
        assert len(state.recent_prices["wood"]) == PRICE_HISTORY_LIMIT

    def test_zero_quantity_safe(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "stone", "quantity": 0, "total_price": 10.0, "buyer": "a", "seller": "b"},
            tick=1,
        )
        assert state.recent_prices["stone"][0].price_per_unit == 0.0


# ── on_narration ─────────────────────────────────────────────────────────────


class TestOnNarration:
    def test_stores_narration(self) -> None:
        state = BridgeState()
        narration = {"headline": "Boom!", "body": "Markets surge", "weather": "booming"}
        state.on_narration(narration)
        assert state.latest_narration is not None
        assert state.latest_narration["headline"] == "Boom!"

    def test_updates_weather(self) -> None:
        state = BridgeState()
        state.on_narration({"weather": "crisis"})
        assert state.market_weather == "crisis"

    def test_overwrites_previous(self) -> None:
        state = BridgeState()
        state.on_narration({"headline": "First", "weather": "stable"})
        state.on_narration({"headline": "Second", "weather": "booming"})
        assert state.latest_narration["headline"] == "Second"
        assert state.market_weather == "booming"


# ── on_nature_event ──────────────────────────────────────────────────────────


class TestOnNatureEvent:
    def test_appends_event(self) -> None:
        state = BridgeState()
        state.on_nature_event({"title": "Drought", "effects": {"potato": 0.5}})
        assert len(state.active_nature_events) == 1
        assert state.active_nature_events[0]["title"] == "Drought"

    def test_multiple_events(self) -> None:
        state = BridgeState()
        state.on_nature_event({"title": "A"})
        state.on_nature_event({"title": "B"})
        assert len(state.active_nature_events) == 2


# ── on_bankruptcy ────────────────────────────────────────────────────────────


class TestOnBankruptcy:
    def test_marks_agent_bankrupt(self) -> None:
        state = BridgeState()
        state.on_bankruptcy({"agent_id": "farmer"})
        assert "farmer" in state.bankrupt_agents

    def test_idempotent(self) -> None:
        state = BridgeState()
        state.on_bankruptcy({"agent_id": "farmer"})
        state.on_bankruptcy({"agent_id": "farmer"})
        assert len(state.bankrupt_agents) == 1


# ── on_rent_due ──────────────────────────────────────────────────────────────


class TestOnRentDue:
    def test_updates_wallet(self) -> None:
        state = BridgeState()
        state.on_rent_due({"agent_id": "chef", "amount": 2.0, "wallet_after": 48.0})
        assert state.agent_wallets["chef"] == 48.0

    def test_overwrites_previous(self) -> None:
        state = BridgeState()
        state.on_rent_due({"agent_id": "chef", "amount": 2.0, "wallet_after": 48.0})
        state.on_rent_due({"agent_id": "chef", "amount": 2.0, "wallet_after": 46.0})
        assert state.agent_wallets["chef"] == 46.0


# ── on_heartbeat ─────────────────────────────────────────────────────────────


class TestOnHeartbeat:
    def test_updates_last_seen(self) -> None:
        state = BridgeState()
        state.on_heartbeat({"agent_id": "farmer", "wallet": 100.0}, tick=15)
        assert state.agent_last_seen["farmer"] == 15

    def test_updates_wallet(self) -> None:
        state = BridgeState()
        state.on_heartbeat({"agent_id": "farmer", "wallet": 95.0}, tick=10)
        assert state.agent_wallets["farmer"] == 95.0

    def test_no_wallet_in_payload(self) -> None:
        state = BridgeState()
        state.agent_wallets["farmer"] = 100.0
        state.on_heartbeat({"agent_id": "farmer"}, tick=10)
        # Should not overwrite
        assert state.agent_wallets["farmer"] == 100.0


# ── on_craft_complete ────────────────────────────────────────────────────────


class TestOnCraftComplete:
    def test_records_craft(self) -> None:
        state = BridgeState()
        state.on_craft_complete({"recipe": "soup", "output": {"soup": 1}, "agent": "chef"})
        assert len(state.recent_crafts) == 1
        assert state.recent_crafts[0]["recipe"] == "soup"

    def test_ring_buffer_limit(self) -> None:
        state = BridgeState()
        for i in range(CRAFT_HISTORY_LIMIT + 5):
            state.on_craft_complete({"recipe": f"r{i}", "output": {"x": 1}})
        assert len(state.recent_crafts) == CRAFT_HISTORY_LIMIT


# ── get_snapshot ─────────────────────────────────────────────────────────────


class TestGetSnapshot:
    def test_empty_state_snapshot(self) -> None:
        state = BridgeState()
        snap = state.get_snapshot()
        assert snap["current_tick"] == 0
        assert snap["active_agents"] == {}
        assert snap["energy_levels"] == {}
        assert snap["agent_wallets"] == {}
        assert snap["recent_prices"] == {}
        assert snap["derived_prices"] == {}
        assert snap["active_nature_events"] == []
        assert snap["market_weather"] == "stable"
        assert snap["latest_narration"] is None
        assert snap["bankrupt_agents"] == []
        assert snap["agent_last_seen"] == {}
        assert snap["recent_crafts"] == []

    def test_snapshot_includes_agents(self) -> None:
        state = BridgeState()
        state.on_join({"agent_id": "farmer", "name": "Farmer", "description": "Grows"}, tick=1)
        snap = state.get_snapshot()
        assert "farmer" in snap["active_agents"]
        assert snap["active_agents"]["farmer"]["name"] == "Farmer"

    def test_snapshot_bankrupt_agents_sorted(self) -> None:
        state = BridgeState()
        state.on_bankruptcy({"agent_id": "chef"})
        state.on_bankruptcy({"agent_id": "baker"})
        snap = state.get_snapshot()
        assert snap["bankrupt_agents"] == ["baker", "chef"]

    def test_snapshot_prices_serialized(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "potato", "quantity": 2, "total_price": 6.0, "buyer": "a", "seller": "b"},
            tick=5,
        )
        snap = state.get_snapshot()
        assert len(snap["recent_prices"]["potato"]) == 1
        assert snap["recent_prices"]["potato"][0]["price_per_unit"] == 3.0


# ── get_derived_prices ───────────────────────────────────────────────────────


class TestGetDerivedPrices:
    def test_empty(self) -> None:
        state = BridgeState()
        assert state.get_derived_prices() == {}

    def test_single_settlement(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "potato", "quantity": 10, "total_price": 20.0, "buyer": "a", "seller": "b"},
            tick=1,
        )
        prices = state.get_derived_prices()
        assert prices["potato"] == 2.0

    def test_weighted_average(self) -> None:
        state = BridgeState()
        # 5 potatoes at 2.0 each = 10.0 total
        state.on_settlement(
            {"item": "potato", "quantity": 5, "total_price": 10.0, "buyer": "a", "seller": "b"},
            tick=1,
        )
        # 10 potatoes at 3.0 each = 30.0 total
        state.on_settlement(
            {"item": "potato", "quantity": 10, "total_price": 30.0, "buyer": "a", "seller": "b"},
            tick=2,
        )
        prices = state.get_derived_prices()
        # weighted avg: (2.0*5 + 3.0*10) / (5+10) = 40/15 = 2.67
        assert prices["potato"] == 2.67

    def test_uses_last_n_records(self) -> None:
        state = BridgeState()
        total = DERIVED_PRICE_WINDOW + 3
        for i in range(total):
            state.on_settlement(
                {"item": "wood", "quantity": 1,
                 "total_price": float(i + 1),
                 "buyer": "a", "seller": "b"},
                tick=i,
            )
        prices = state.get_derived_prices()
        # Should only use last DERIVED_PRICE_WINDOW records
        start = total - DERIVED_PRICE_WINDOW + 1
        expected_values = list(range(start, total + 1))
        expected = round(sum(expected_values) / len(expected_values), 2)
        assert prices["wood"] == expected
