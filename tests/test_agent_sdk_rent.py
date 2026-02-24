"""Tests for Agent SDK updates — rent, bankruptcy, storage, nature events."""

from streetmarket.agent.state import AgentState
from streetmarket.models.rent import STORAGE_BASE_LIMIT, STORAGE_MAX_SHELVES, STORAGE_PER_SHELF

# ── AgentState new fields ──────────────────────────────────────────────────


class TestAgentStateNewFields:
    def test_rent_due_default_zero(self) -> None:
        state = AgentState(agent_id="test")
        assert state.rent_due_this_tick == 0.0

    def test_is_bankrupt_default_false(self) -> None:
        state = AgentState(agent_id="test")
        assert state.is_bankrupt is False

    def test_storage_limit_default(self) -> None:
        state = AgentState(agent_id="test")
        assert state.storage_limit == 50

    def test_total_inventory_empty(self) -> None:
        state = AgentState(agent_id="test")
        assert state.total_inventory() == 0

    def test_total_inventory_with_items(self) -> None:
        state = AgentState(agent_id="test", inventory={"potato": 10, "onion": 5})
        assert state.total_inventory() == 15

    def test_storage_remaining_full(self) -> None:
        state = AgentState(agent_id="test")
        assert state.storage_remaining() == 50

    def test_storage_remaining_partial(self) -> None:
        state = AgentState(agent_id="test", inventory={"potato": 30})
        assert state.storage_remaining() == 20

    def test_storage_remaining_at_limit(self) -> None:
        state = AgentState(agent_id="test", inventory={"potato": 50})
        assert state.storage_remaining() == 0

    def test_storage_remaining_over_limit(self) -> None:
        state = AgentState(agent_id="test", inventory={"potato": 60}, storage_limit=50)
        assert state.storage_remaining() == 0

    def test_advance_tick_resets_rent_due(self) -> None:
        state = AgentState(agent_id="test")
        state.rent_due_this_tick = 2.0
        state.advance_tick(5)
        assert state.rent_due_this_tick == 0.0

    def test_advance_tick_does_not_reset_bankrupt(self) -> None:
        state = AgentState(agent_id="test")
        state.is_bankrupt = True
        state.advance_tick(5)
        assert state.is_bankrupt is True


# ── Storage limit with shelves ──────────────────────────────────────────────


class TestStorageLimitWithShelves:
    def test_storage_limit_with_shelves(self) -> None:
        state = AgentState(
            agent_id="test",
            inventory={"shelf": 2},
            storage_limit=STORAGE_BASE_LIMIT + 2 * STORAGE_PER_SHELF,
        )
        assert state.storage_limit == 70

    def test_storage_remaining_with_shelves(self) -> None:
        state = AgentState(
            agent_id="test",
            inventory={"shelf": 2, "potato": 10},
            storage_limit=STORAGE_BASE_LIMIT + 2 * STORAGE_PER_SHELF,
        )
        # 70 - 12 = 58
        assert state.storage_remaining() == 58

    def test_max_storage_with_max_shelves(self) -> None:
        max_storage = STORAGE_BASE_LIMIT + STORAGE_MAX_SHELVES * STORAGE_PER_SHELF
        state = AgentState(
            agent_id="test",
            storage_limit=max_storage,
        )
        assert state.storage_remaining() == 80
