"""Tests for BridgeState — aggregate state for WebSocket snapshots."""

from __future__ import annotations

from services.websocket_bridge.state import (
    CRAFT_HISTORY_LIMIT,
    DERIVED_PRICE_WINDOW,
    NARRATION_HISTORY_LIMIT,
    PRICE_HISTORY_LIMIT,
    AgentInfo,
    AgentScoreTracker,
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
        assert len(state.narration_history) == 0
        assert state.energy_deltas == {}
        assert state.town_treasury == 0.0
        assert state.total_rent_collected == 0.0
        assert state.agent_inventories == {}


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

    def test_initializes_wallet_on_join(self) -> None:
        state = BridgeState()
        state.on_join({"agent_id": "farmer", "name": "Farmer", "description": ""}, tick=1)
        assert state.agent_wallets["farmer"] == 100.0

    def test_does_not_overwrite_existing_wallet(self) -> None:
        state = BridgeState()
        state.agent_wallets["farmer"] = 85.0
        state.on_join({"agent_id": "farmer", "name": "Farmer", "description": ""}, tick=1)
        assert state.agent_wallets["farmer"] == 85.0


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

    def test_appends_to_history(self) -> None:
        state = BridgeState()
        state.on_narration({"headline": "First", "weather": "stable"})
        state.on_narration({"headline": "Second", "weather": "booming"})
        assert len(state.narration_history) == 2
        assert state.narration_history[0]["headline"] == "First"
        assert state.narration_history[1]["headline"] == "Second"

    def test_history_ring_buffer(self) -> None:
        state = BridgeState()
        for i in range(NARRATION_HISTORY_LIMIT + 5):
            state.on_narration({"headline": f"H{i}", "weather": "stable"})
        assert len(state.narration_history) == NARRATION_HISTORY_LIMIT

    def test_snapshot_includes_narrations(self) -> None:
        state = BridgeState()
        state.on_narration({"headline": "A", "weather": "stable"})
        state.on_narration({"headline": "B", "weather": "booming"})
        snap = state.get_snapshot()
        assert len(snap["narrations"]) == 2
        assert snap["narrations"][0]["headline"] == "A"


# ── on_nature_event ──────────────────────────────────────────────────────────


class TestOnNatureEvent:
    def test_appends_event(self) -> None:
        state = BridgeState()
        state.on_nature_event({"title": "Drought", "effects": {"potato": 0.5}, "duration_ticks": 5})
        assert len(state.active_nature_events) == 1
        assert state.active_nature_events[0]["title"] == "Drought"

    def test_multiple_events(self) -> None:
        state = BridgeState()
        state.on_nature_event({"title": "A", "duration_ticks": 5})
        state.on_nature_event({"title": "B", "duration_ticks": 3})
        assert len(state.active_nature_events) == 2

    def test_computes_end_tick(self) -> None:
        state = BridgeState()
        state.on_tick(10)
        state.on_nature_event({"title": "Flood", "duration_ticks": 5})
        assert state.active_nature_events[0]["end_tick"] == 15

    def test_expired_events_pruned_on_tick(self) -> None:
        state = BridgeState()
        state.on_tick(10)
        state.on_nature_event({"title": "Short", "duration_ticks": 2})
        state.on_nature_event({"title": "Long", "duration_ticks": 20})
        assert len(state.active_nature_events) == 2
        state.on_tick(13)  # Short event (end_tick=12) expired
        assert len(state.active_nature_events) == 1
        assert state.active_nature_events[0]["title"] == "Long"


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

    def test_updates_inventory_count(self) -> None:
        state = BridgeState()
        state.on_heartbeat({"agent_id": "farmer", "wallet": 90.0, "inventory_count": 15}, tick=5)
        assert state.agent_inventories["farmer"] == 15


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
        assert snap["narrations"] == []
        assert snap["energy_deltas"] == {}
        assert snap["town_treasury"] == 0.0
        assert snap["total_rent_collected"] == 0.0
        assert snap["agent_inventories"] == {}

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


# ── Energy deltas ───────────────────────────────────────────────────────


class TestEnergyDeltas:
    def test_first_update_zero_deltas(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 100.0}})
        assert state.energy_deltas["farmer"] == 0.0

    def test_positive_delta(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 80.0}})
        state.on_energy_update({"energy_levels": {"farmer": 85.0}})
        assert state.energy_deltas["farmer"] == 5.0

    def test_negative_delta(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 80.0}})
        state.on_energy_update({"energy_levels": {"farmer": 70.0}})
        assert state.energy_deltas["farmer"] == -10.0

    def test_snapshot_includes_deltas(self) -> None:
        state = BridgeState()
        state.on_energy_update({"energy_levels": {"farmer": 80.0}})
        state.on_energy_update({"energy_levels": {"farmer": 85.0}})
        snap = state.get_snapshot()
        assert snap["energy_deltas"]["farmer"] == 5.0


# ── Rent / Treasury tracking ───────────────────────────────────────────


class TestRentTracking:
    def test_tracks_treasury_from_rent(self) -> None:
        state = BridgeState()
        state.on_rent_due({
            "agent_id": "chef",
            "amount": 0.5,
            "wallet_after": 99.5,
            "treasury_balance": 0.5,
            "total_rent_collected": 0.5,
        })
        assert state.town_treasury == 0.5
        assert state.total_rent_collected == 0.5

    def test_treasury_accumulates(self) -> None:
        state = BridgeState()
        state.on_rent_due({
            "agent_id": "chef",
            "amount": 0.5,
            "wallet_after": 99.5,
            "treasury_balance": 0.5,
            "total_rent_collected": 0.5,
        })
        state.on_rent_due({
            "agent_id": "farmer",
            "amount": 0.5,
            "wallet_after": 99.5,
            "treasury_balance": 1.0,
            "total_rent_collected": 1.0,
        })
        assert state.town_treasury == 1.0
        assert state.total_rent_collected == 1.0

    def test_snapshot_includes_treasury(self) -> None:
        state = BridgeState()
        state.on_rent_due({
            "agent_id": "chef",
            "amount": 0.5,
            "wallet_after": 99.5,
            "treasury_balance": 0.5,
            "total_rent_collected": 0.5,
        })
        snap = state.get_snapshot()
        assert snap["town_treasury"] == 0.5
        assert snap["total_rent_collected"] == 0.5


# ── Settlement wallet updates ──────────────────────────────────────────


class TestSettlementWallets:
    def test_updates_wallets_from_settlement(self) -> None:
        state = BridgeState()
        state.on_settlement({
            "item": "potato",
            "quantity": 5,
            "total_price": 10.0,
            "buyer": "chef",
            "seller": "farmer",
            "buyer_wallet_after": 90.0,
            "seller_wallet_after": 110.0,
        }, tick=10)
        assert state.agent_wallets["chef"] == 90.0
        assert state.agent_wallets["farmer"] == 110.0

    def test_no_wallet_fields_doesnt_overwrite(self) -> None:
        state = BridgeState()
        state.agent_wallets["chef"] = 95.0
        state.on_settlement({
            "item": "potato",
            "quantity": 5,
            "total_price": 10.0,
            "buyer": "chef",
            "seller": "farmer",
        }, tick=10)
        # Without wallet_after fields, shouldn't update
        assert state.agent_wallets["chef"] == 95.0


# ── Inventory tracking ─────────────────────────────────────────────────


class TestInventoryTracking:
    def test_tracks_from_heartbeat(self) -> None:
        state = BridgeState()
        state.on_heartbeat({"agent_id": "farmer", "wallet": 100.0, "inventory_count": 25}, tick=5)
        assert state.agent_inventories["farmer"] == 25

    def test_snapshot_includes_inventories(self) -> None:
        state = BridgeState()
        state.on_heartbeat({"agent_id": "farmer", "wallet": 100.0, "inventory_count": 10}, tick=5)
        snap = state.get_snapshot()
        assert snap["agent_inventories"]["farmer"] == 10


# ── AgentScoreTracker ─────────────────────────────────────────────────


class TestAgentScoreTracker:
    def test_defaults(self) -> None:
        t = AgentScoreTracker()
        assert t.decisions_total == 0
        assert t.decisions_with_thoughts == 0
        assert t.decisions_with_speech == 0
        assert t.moods_seen == set()
        assert t.trade_actions == 0
        assert t.settlements == 0
        assert t.crafts_completed == 0
        assert t.total_actions == 0


# ── Score tracking — counter accumulation ─────────────────────────────


class TestScoreTracking:
    def test_agent_status_increments_decisions(self) -> None:
        state = BridgeState()
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "hmm", "speech": "hey", "mood": "happy", "action_count": 2},
            tick=1,
        )
        t = state.agent_score_trackers["farmer"]
        assert t.decisions_total == 1
        assert t.decisions_with_thoughts == 1
        assert t.decisions_with_speech == 1
        assert t.moods_seen == {"happy"}
        assert t.total_actions == 2

    def test_empty_thoughts_not_counted(self) -> None:
        state = BridgeState()
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "", "speech": "hi", "mood": "calm", "action_count": 1},
            tick=1,
        )
        t = state.agent_score_trackers["farmer"]
        assert t.decisions_with_thoughts == 0
        assert t.decisions_with_speech == 1

    def test_empty_speech_not_counted(self) -> None:
        state = BridgeState()
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "thinking", "speech": "", "mood": "calm", "action_count": 0},
            tick=1,
        )
        t = state.agent_score_trackers["farmer"]
        assert t.decisions_with_thoughts == 1
        assert t.decisions_with_speech == 0

    def test_multiple_moods_tracked(self) -> None:
        state = BridgeState()
        for mood in ["happy", "calm", "frustrated", "happy"]:
            state.on_agent_status(
                {"agent_id": "farmer", "thoughts": "x", "speech": "", "mood": mood, "action_count": 0},
                tick=1,
            )
        t = state.agent_score_trackers["farmer"]
        assert t.moods_seen == {"happy", "calm", "frustrated"}
        assert t.decisions_total == 4

    def test_settlement_increments_both_parties(self) -> None:
        state = BridgeState()
        state.on_settlement(
            {"item": "potato", "quantity": 5, "total_price": 10.0, "buyer": "chef", "seller": "farmer"},
            tick=10,
        )
        assert state.agent_score_trackers["chef"].settlements == 1
        assert state.agent_score_trackers["farmer"].settlements == 1

    def test_craft_complete_increments_tracker(self) -> None:
        state = BridgeState()
        state.on_craft_complete({"recipe": "soup", "output": {"soup": 1}, "agent_id": "chef"})
        assert state.agent_score_trackers["chef"].crafts_completed == 1

    def test_craft_complete_uses_agent_field_fallback(self) -> None:
        state = BridgeState()
        state.on_craft_complete({"recipe": "soup", "output": {"soup": 1}, "agent": "chef"})
        assert state.agent_score_trackers["chef"].crafts_completed == 1

    def test_trade_action_increments_counter(self) -> None:
        state = BridgeState()
        state.on_trade_action("farmer")
        state.on_trade_action("farmer")
        state.on_trade_action("chef")
        assert state.agent_score_trackers["farmer"].trade_actions == 2
        assert state.agent_score_trackers["chef"].trade_actions == 1

    def test_trade_action_empty_agent_ignored(self) -> None:
        state = BridgeState()
        state.on_trade_action("")
        assert len(state.agent_score_trackers) == 0

    def test_bankrupt_agent_scores_frozen(self) -> None:
        """Bankrupt agents' score trackers must not accumulate new events."""
        state = BridgeState()
        # Build some score before bankruptcy
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "ok", "speech": "hi", "mood": "happy", "action_count": 1},
            tick=1,
        )
        assert state.agent_score_trackers["farmer"].decisions_total == 1

        # Mark bankrupt
        state.on_bankruptcy({"agent_id": "farmer"})

        # All score-updating events should be ignored
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "x", "speech": "y", "mood": "angry", "action_count": 3},
            tick=2,
        )
        state.on_trade_action("farmer")
        state.on_craft_complete({"recipe": "soup", "output": {"soup": 1}, "agent_id": "farmer"})
        state.on_settlement(
            {"item": "potato", "quantity": 5, "total_price": 10.0, "buyer": "farmer", "seller": "chef"},
            tick=3,
        )

        # Score frozen at pre-bankruptcy values
        t = state.agent_score_trackers["farmer"]
        assert t.decisions_total == 1
        assert t.trade_actions == 0
        assert t.crafts_completed == 0
        assert t.settlements == 0
        assert t.moods_seen == {"happy"}  # "angry" not added

    def test_bankrupt_seller_score_frozen_but_buyer_updates(self) -> None:
        """When a bankrupt agent is one party in a settlement, only the other party's score updates."""
        state = BridgeState()
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "ok", "speech": "", "mood": "calm", "action_count": 0},
            tick=1,
        )
        state.on_bankruptcy({"agent_id": "farmer"})

        state.on_settlement(
            {"item": "potato", "quantity": 2, "total_price": 4.0, "buyer": "chef", "seller": "farmer"},
            tick=5,
        )
        assert state.agent_score_trackers["farmer"].settlements == 0  # frozen
        assert state.agent_score_trackers["chef"].settlements == 1  # active


# ── Score computation ─────────────────────────────────────────────────


class TestScoreComputation:
    def test_no_decisions_returns_zeros(self) -> None:
        state = BridgeState()
        state.agent_score_trackers["farmer"] = AgentScoreTracker()
        scores = state.compute_agent_scores()
        assert scores["farmer"]["total"] == 0
        assert scores["farmer"]["expressiveness"] == 0

    def test_full_expressiveness(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, decisions_with_thoughts=10, decisions_with_speech=5)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["expressiveness"] == 100  # max(10/10, 5/10) = 1.0 → 100

    def test_half_expressiveness(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, decisions_with_thoughts=5, decisions_with_speech=3)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["expressiveness"] == 50  # max(5/10, 3/10) = 0.5 → 50

    def test_social_balanced_speech(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, decisions_with_speech=5)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        # 50% speech rate → center of sweet spot → 100
        assert scores["farmer"]["social"] == 100

    def test_social_no_speech(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, decisions_with_speech=0)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["social"] == 0

    def test_social_extreme_high_speech(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, decisions_with_speech=10)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        # 100% → penalty zone (>0.9)
        assert scores["farmer"]["social"] == 0

    def test_character_mood_variety(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=5, moods_seen={"happy", "calm", "frustrated"})
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["character"] == 60  # 3 moods × 20

    def test_character_capped_at_100(self) -> None:
        state = BridgeState()
        moods = {"happy", "calm", "frustrated", "excited", "worried", "bored"}
        t = AgentScoreTracker(decisions_total=6, moods_seen=moods)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["character"] == 100

    def test_trading_score(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=10, trade_actions=3, settlements=2)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        # (3 + 2*2) / 10 * 100 = 70
        assert scores["farmer"]["trading"] == 70

    def test_trading_capped_at_100(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=2, trade_actions=5, settlements=3)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        assert scores["farmer"]["trading"] == 100

    def test_total_is_average(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(
            decisions_total=10,
            decisions_with_thoughts=10,  # expressiveness=100
            decisions_with_speech=5,      # social=100 (50% rate)
            moods_seen={"happy", "calm", "frustrated", "excited", "worried"},  # character=100
            trade_actions=3,
            settlements=2,  # trading=70
        )
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        expected_total = round((100 + 100 + 100 + 70) / 4)
        assert scores["farmer"]["total"] == expected_total

    def test_counters_in_scores(self) -> None:
        state = BridgeState()
        t = AgentScoreTracker(decisions_total=5, moods_seen={"happy", "calm"}, trade_actions=2)
        state.agent_score_trackers["farmer"] = t
        scores = state.compute_agent_scores()
        counters = scores["farmer"]["counters"]
        assert counters["decisions_total"] == 5
        assert counters["moods_seen"] == ["calm", "happy"]  # sorted
        assert counters["trade_actions"] == 2

    def test_snapshot_includes_agent_scores(self) -> None:
        state = BridgeState()
        state.on_agent_status(
            {"agent_id": "farmer", "thoughts": "hmm", "speech": "hey", "mood": "happy", "action_count": 1},
            tick=1,
        )
        snap = state.get_snapshot()
        assert "agent_scores" in snap
        assert "farmer" in snap["agent_scores"]
        assert snap["agent_scores"]["farmer"]["expressiveness"] == 100


class TestItemSpoiledBridgeState:
    def test_on_item_spoiled_records_event(self) -> None:
        state = BridgeState()
        state.on_item_spoiled({"agent_id": "farmer", "item": "potato", "quantity": 5})
        assert len(state.recent_spoilage) == 1
        assert state.recent_spoilage[0]["item"] == "potato"

    def test_snapshot_includes_spoilage(self) -> None:
        state = BridgeState()
        state.on_item_spoiled({"agent_id": "farmer", "item": "potato", "quantity": 3})
        snap = state.get_snapshot()
        assert "recent_spoilage" in snap
        assert len(snap["recent_spoilage"]) == 1
        assert snap["recent_spoilage"][0]["agent_id"] == "farmer"

    def test_spoilage_ring_buffer(self) -> None:
        state = BridgeState()
        for i in range(25):
            state.on_item_spoiled({"agent_id": "farmer", "item": "potato", "quantity": i})
        # maxlen=CRAFT_HISTORY_LIMIT (20)
        assert len(state.recent_spoilage) == 20
