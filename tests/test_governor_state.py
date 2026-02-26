"""Tests for Governor in-memory state tracking."""

from services.governor.state import (
    HEARTBEAT_TIMEOUT_TICKS,
    MAX_ACTIONS_PER_TICK,
    SERVICE_IDS,
    GovernorState,
)


class TestTickAdvancement:
    def test_advance_tick_updates_current_tick(self):
        state = GovernorState()
        state.advance_tick(5)
        assert state.current_tick == 5

    def test_advance_tick_resets_action_counts(self):
        state = GovernorState()
        state.record_action("agent-1")
        state.record_action("agent-1")
        assert state.get_action_count("agent-1") == 2
        state.advance_tick(1)
        assert state.get_action_count("agent-1") == 0


class TestRateLimiting:
    def test_no_actions_not_limited(self):
        state = GovernorState()
        assert not state.is_rate_limited("agent-1")

    def test_under_limit_not_limited(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK - 1):
            state.record_action("agent-1")
        assert not state.is_rate_limited("agent-1")

    def test_at_limit_is_limited(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK):
            state.record_action("agent-1")
        assert state.is_rate_limited("agent-1")

    def test_over_limit_is_limited(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK + 1):
            state.record_action("agent-1")
        assert state.is_rate_limited("agent-1")

    def test_rate_limit_is_per_agent(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK):
            state.record_action("agent-1")
        assert state.is_rate_limited("agent-1")
        assert not state.is_rate_limited("agent-2")

    def test_rate_limit_resets_on_tick(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK):
            state.record_action("agent-1")
        assert state.is_rate_limited("agent-1")
        state.advance_tick(1)
        assert not state.is_rate_limited("agent-1")

    def test_services_exempt_from_rate_limit(self):
        """Infrastructure services (banker, world, etc.) are never rate-limited."""
        state = GovernorState()
        for service_id in SERVICE_IDS:
            for _ in range(MAX_ACTIONS_PER_TICK + 10):
                state.record_action(service_id)
            assert not state.is_rate_limited(service_id), f"{service_id} should be exempt"

    def test_banker_not_rate_limited_after_many_actions(self):
        """Banker processes many settlements per tick — must not be rate-limited."""
        state = GovernorState()
        for _ in range(50):
            state.record_action("banker")
        assert not state.is_rate_limited("banker")

    def test_service_ids_contains_all_services(self):
        """Verify all known service IDs are in the exemption set."""
        expected = {"banker", "world", "governor", "town_crier", "websocket_bridge"}
        assert SERVICE_IDS == expected


class TestMarketOpen:
    def test_market_closed_initially(self):
        state = GovernorState()
        assert not state.market_open

    def test_market_opens_on_first_tick(self):
        state = GovernorState()
        state.advance_tick(1)
        assert state.market_open

    def test_market_stays_open(self):
        state = GovernorState()
        state.advance_tick(1)
        state.advance_tick(2)
        assert state.market_open


class TestHeartbeats:
    def test_unknown_agent_not_inactive(self):
        state = GovernorState()
        assert not state.is_inactive("agent-1")

    def test_recent_heartbeat_not_inactive(self):
        state = GovernorState()
        state.advance_tick(5)
        state.record_heartbeat("agent-1")
        state.advance_tick(10)
        assert not state.is_inactive("agent-1")

    def test_stale_heartbeat_is_inactive(self):
        state = GovernorState()
        state.advance_tick(0)
        state.record_heartbeat("agent-1")
        state.advance_tick(HEARTBEAT_TIMEOUT_TICKS + 1)
        assert state.is_inactive("agent-1")

    def test_exactly_at_timeout_not_inactive(self):
        state = GovernorState()
        state.advance_tick(0)
        state.record_heartbeat("agent-1")
        state.advance_tick(HEARTBEAT_TIMEOUT_TICKS)
        assert not state.is_inactive("agent-1")

    def test_heartbeat_refreshes_timer(self):
        state = GovernorState()
        state.advance_tick(0)
        state.record_heartbeat("agent-1")
        state.advance_tick(HEARTBEAT_TIMEOUT_TICKS - 1)
        state.record_heartbeat("agent-1")
        state.advance_tick(HEARTBEAT_TIMEOUT_TICKS * 2 - 2)
        assert not state.is_inactive("agent-1")


class TestAgentRegistration:
    def test_unknown_agent(self):
        state = GovernorState()
        assert not state.is_known_agent("agent-1")

    def test_registered_agent(self):
        state = GovernorState()
        state.register_agent("agent-1")
        assert state.is_known_agent("agent-1")


class TestCrafting:
    def test_not_crafting_initially(self):
        state = GovernorState()
        assert not state.is_crafting("agent-1")
        assert state.get_active_craft("agent-1") is None

    def test_start_craft(self):
        state = GovernorState()
        state.advance_tick(5)
        state.start_craft("agent-1", "soup", 2)
        assert state.is_crafting("agent-1")
        craft = state.get_active_craft("agent-1")
        assert craft is not None
        assert craft.recipe == "soup"
        assert craft.started_tick == 5
        assert craft.estimated_ticks == 2

    def test_complete_craft(self):
        state = GovernorState()
        state.start_craft("agent-1", "soup", 2)
        craft = state.complete_craft("agent-1")
        assert craft is not None
        assert craft.recipe == "soup"
        assert not state.is_crafting("agent-1")

    def test_complete_craft_when_not_crafting(self):
        state = GovernorState()
        assert state.complete_craft("agent-1") is None

    def test_start_craft_replaces_existing(self):
        state = GovernorState()
        state.start_craft("agent-1", "soup", 2)
        state.start_craft("agent-1", "shelf", 3)
        craft = state.get_active_craft("agent-1")
        assert craft is not None
        assert craft.recipe == "shelf"
