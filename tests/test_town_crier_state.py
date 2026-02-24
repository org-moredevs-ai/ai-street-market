"""Tests for TownCrierState — event accumulation and market weather."""

from __future__ import annotations

from streetmarket import MarketWeather

from services.town_crier.state import (
    NARRATION_INTERVAL,
    TownCrierState,
)

# ── Tick management ──────────────────────────────────────────────────────────


class TestTickManagement:
    def test_advance_tick(self) -> None:
        state = TownCrierState()
        state.advance_tick(10)
        assert state.current_tick == 10

    def test_advance_tick_multiple(self) -> None:
        state = TownCrierState()
        state.advance_tick(5)
        state.advance_tick(10)
        assert state.current_tick == 10

    def test_initial_tick_is_zero(self) -> None:
        state = TownCrierState()
        assert state.current_tick == 0


# ── Should narrate ───────────────────────────────────────────────────────────


class TestShouldNarrate:
    def test_narrate_at_interval(self) -> None:
        state = TownCrierState()
        assert state.should_narrate(NARRATION_INTERVAL) is True

    def test_no_narrate_at_tick_zero(self) -> None:
        state = TownCrierState()
        assert state.should_narrate(0) is False

    def test_no_narrate_between_intervals(self) -> None:
        state = TownCrierState()
        assert state.should_narrate(3) is False

    def test_narrate_at_multiple_of_interval(self) -> None:
        state = TownCrierState()
        assert state.should_narrate(NARRATION_INTERVAL * 3) is True

    def test_narration_interval_is_five(self) -> None:
        assert NARRATION_INTERVAL == 5


# ── Settlement recording ─────────────────────────────────────────────────────


class TestSettlementRecording:
    def test_record_settlement(self) -> None:
        state = TownCrierState()
        state.record_settlement("buyer1", "seller1", "potato", 5, 10.0)
        assert len(state.settlements) == 1
        assert state.settlements[0].buyer == "buyer1"
        assert state.settlements[0].item == "potato"

    def test_settlement_updates_totals(self) -> None:
        state = TownCrierState()
        state.record_settlement("b", "s", "potato", 1, 5.0)
        state.record_settlement("b", "s", "onion", 2, 8.0)
        assert state.total_settlements == 2
        assert state.total_coins_traded == 13.0

    def test_settlement_totals_survive_reset(self) -> None:
        state = TownCrierState()
        state.record_settlement("b", "s", "potato", 1, 10.0)
        state.reset_window()
        assert state.total_settlements == 1
        assert state.total_coins_traded == 10.0
        assert len(state.settlements) == 0


# ── Bankruptcy recording ─────────────────────────────────────────────────────


class TestBankruptcyRecording:
    def test_record_bankruptcy(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("farmer")
        assert state.bankruptcies == ["farmer"]

    def test_multiple_bankruptcies(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("farmer")
        state.record_bankruptcy("chef")
        assert len(state.bankruptcies) == 2

    def test_bankruptcies_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("farmer")
        state.reset_window()
        assert len(state.bankruptcies) == 0


# ── Nature event recording ───────────────────────────────────────────────────


class TestNatureEventRecording:
    def test_record_nature_event(self) -> None:
        state = TownCrierState()
        state.record_nature_event("Drought", "Water dries up")
        assert len(state.nature_events) == 1
        assert state.nature_events[0]["title"] == "Drought"

    def test_nature_events_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.record_nature_event("Flood", "Rain pours")
        state.reset_window()
        assert len(state.nature_events) == 0


# ── Energy tracking ──────────────────────────────────────────────────────────


class TestEnergyTracking:
    def test_update_energy(self) -> None:
        state = TownCrierState()
        state.update_energy({"farmer": 80.0, "chef": 60.0})
        assert state.energy_levels == {"farmer": 80.0, "chef": 60.0}

    def test_update_energy_overwrites(self) -> None:
        state = TownCrierState()
        state.update_energy({"farmer": 80.0})
        state.update_energy({"farmer": 50.0, "chef": 70.0})
        assert state.energy_levels == {"farmer": 50.0, "chef": 70.0}

    def test_energy_not_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.update_energy({"farmer": 80.0})
        state.reset_window()
        # Energy is a snapshot, not an accumulator — it stays
        assert state.energy_levels == {"farmer": 80.0}


# ── Rent recording ───────────────────────────────────────────────────────────


class TestRentRecording:
    def test_record_rent(self) -> None:
        state = TownCrierState()
        state.record_rent("farmer", 2.0, 48.0)
        assert len(state.rent_payments) == 1
        assert state.rent_payments[0].amount == 2.0

    def test_rent_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.record_rent("farmer", 2.0, 48.0)
        state.reset_window()
        assert len(state.rent_payments) == 0


# ── Activity recording ───────────────────────────────────────────────────────


class TestActivityRecording:
    def test_record_activity(self) -> None:
        state = TownCrierState()
        state.record_activity("farmer")
        assert state.activity_counts["farmer"] == 1

    def test_record_activity_increments(self) -> None:
        state = TownCrierState()
        state.record_activity("farmer")
        state.record_activity("farmer")
        state.record_activity("chef")
        assert state.activity_counts["farmer"] == 2
        assert state.activity_counts["chef"] == 1

    def test_activity_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.record_activity("farmer")
        state.reset_window()
        assert len(state.activity_counts) == 0


# ── Join recording ───────────────────────────────────────────────────────────


class TestJoinRecording:
    def test_record_join(self) -> None:
        state = TownCrierState()
        state.record_join("farmer")
        assert state.joins == ["farmer"]

    def test_joins_cleared_on_reset(self) -> None:
        state = TownCrierState()
        state.record_join("farmer")
        state.reset_window()
        assert len(state.joins) == 0


# ── Craft recording ──────────────────────────────────────────────────────────


class TestCraftRecording:
    def test_record_craft(self) -> None:
        state = TownCrierState()
        state.record_craft("chef", "soup", "soup", 1)
        assert len(state.crafts) == 1
        assert state.crafts[0].recipe == "soup"

    def test_craft_updates_all_time(self) -> None:
        state = TownCrierState()
        state.record_craft("chef", "soup", "soup")
        state.record_craft("chef", "soup", "soup")
        assert state.total_crafts == 2
        assert state.all_time_crafts["soup"] == 2

    def test_craft_all_time_survives_reset(self) -> None:
        state = TownCrierState()
        state.record_craft("chef", "soup", "soup")
        state.reset_window()
        assert state.total_crafts == 1
        assert state.all_time_crafts["soup"] == 1
        assert len(state.crafts) == 0


# ── Market weather computation ───────────────────────────────────────────────


class TestMarketWeather:
    def test_default_is_stable(self) -> None:
        state = TownCrierState()
        assert state.compute_market_weather() == MarketWeather.STABLE

    def test_crisis_on_multiple_bankruptcies(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("farmer")
        state.record_bankruptcy("chef")
        assert state.compute_market_weather() == MarketWeather.CRISIS

    def test_crisis_on_majority_stressed(self) -> None:
        state = TownCrierState()
        state.update_energy({"a": 10.0, "b": 15.0, "c": 80.0})
        # 2 out of 3 stressed (<30) = majority
        assert state.compute_market_weather() == MarketWeather.CRISIS

    def test_chaotic_on_price_spread(self) -> None:
        state = TownCrierState()
        # potato base_price = 2.0; sell at 1.0 and 10.0 per unit = 10x spread
        state.record_settlement("b1", "s1", "potato", 1, 1.0)
        state.record_settlement("b2", "s2", "potato", 1, 10.0)
        assert state.compute_market_weather() == MarketWeather.CHAOTIC

    def test_chaotic_on_extreme_vs_base(self) -> None:
        state = TownCrierState()
        # potato base_price=2.0, selling at 7.0 per unit (>3x base)
        state.record_settlement("b1", "s1", "potato", 1, 2.0)
        state.record_settlement("b2", "s2", "potato", 1, 7.0)
        assert state.compute_market_weather() == MarketWeather.CHAOTIC

    def test_stressed_on_low_avg_energy(self) -> None:
        state = TownCrierState()
        state.update_energy({"a": 30.0, "b": 35.0, "c": 40.0})
        # avg = 35 < 40
        assert state.compute_market_weather() == MarketWeather.STRESSED

    def test_stressed_on_two_stressed_agents(self) -> None:
        state = TownCrierState()
        state.update_energy({"a": 20.0, "b": 25.0, "c": 80.0, "d": 90.0})
        # 2 agents <30
        assert state.compute_market_weather() == MarketWeather.STRESSED

    def test_booming_on_high_trade_and_energy(self) -> None:
        state = TownCrierState()
        state.update_energy({"a": 80.0, "b": 70.0})
        state.record_settlement("a", "b", "potato", 1, 2.0)
        state.record_settlement("a", "b", "onion", 1, 2.0)
        state.record_settlement("a", "b", "wood", 1, 3.0)
        assert state.compute_market_weather() == MarketWeather.BOOMING

    def test_stable_with_few_trades(self) -> None:
        state = TownCrierState()
        state.update_energy({"a": 80.0, "b": 70.0})
        state.record_settlement("a", "b", "potato", 1, 2.0)
        # Only 1 trade, not enough for BOOMING
        assert state.compute_market_weather() == MarketWeather.STABLE

    def test_crisis_takes_priority_over_chaotic(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("farmer")
        state.record_bankruptcy("chef")
        # Also add price variance
        state.record_settlement("b1", "s1", "potato", 1, 1.0)
        state.record_settlement("b2", "s2", "potato", 1, 10.0)
        assert state.compute_market_weather() == MarketWeather.CRISIS


# ── Window summary ───────────────────────────────────────────────────────────


class TestWindowSummary:
    def test_empty_summary(self) -> None:
        state = TownCrierState()
        state.advance_tick(5)
        summary = state.get_window_summary()
        assert summary["window_start_tick"] == 0
        assert summary["window_end_tick"] == 5
        assert summary["settlements"] == []
        assert summary["weather"] == MarketWeather.STABLE

    def test_summary_includes_settlements(self) -> None:
        state = TownCrierState()
        state.record_settlement("buyer", "seller", "potato", 5, 10.0)
        summary = state.get_window_summary()
        assert len(summary["settlements"]) == 1
        assert summary["settlements"][0]["buyer"] == "buyer"

    def test_summary_includes_all_time_stats(self) -> None:
        state = TownCrierState()
        state.record_settlement("b", "s", "potato", 1, 5.0)
        state.record_craft("chef", "soup", "soup")
        summary = state.get_window_summary()
        assert summary["total_settlements"] == 1
        assert summary["total_crafts"] == 1
        assert summary["total_coins_traded"] == 5.0

    def test_summary_includes_weather(self) -> None:
        state = TownCrierState()
        state.record_bankruptcy("a")
        state.record_bankruptcy("b")
        summary = state.get_window_summary()
        assert summary["weather"] == MarketWeather.CRISIS


# ── Reset window ─────────────────────────────────────────────────────────────


class TestResetWindow:
    def test_reset_clears_per_window(self) -> None:
        state = TownCrierState()
        state.advance_tick(5)
        state.record_settlement("b", "s", "potato", 1, 5.0)
        state.record_bankruptcy("farmer")
        state.record_nature_event("Flood", "Rain")
        state.record_rent("farmer", 2.0, 48.0)
        state.record_craft("chef", "soup", "soup")
        state.record_join("farmer")
        state.record_activity("farmer")
        state.reset_window()

        assert len(state.settlements) == 0
        assert len(state.bankruptcies) == 0
        assert len(state.nature_events) == 0
        assert len(state.rent_payments) == 0
        assert len(state.crafts) == 0
        assert len(state.joins) == 0
        assert len(state.activity_counts) == 0

    def test_reset_preserves_all_time(self) -> None:
        state = TownCrierState()
        state.record_settlement("b", "s", "potato", 1, 5.0)
        state.record_craft("chef", "soup", "soup")
        state.reset_window()

        assert state.total_settlements == 1
        assert state.total_crafts == 1
        assert state.total_coins_traded == 5.0
        assert state.all_time_crafts == {"soup": 1}

    def test_reset_updates_window_start(self) -> None:
        state = TownCrierState()
        state.advance_tick(10)
        state.reset_window()
        assert state.window_start_tick == 10
