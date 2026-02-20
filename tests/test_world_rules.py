"""Unit tests for World Engine rules."""

from streetmarket import Envelope, MessageType

from services.world.rules import process_gather, process_tick
from services.world.state import DEFAULT_SPAWN_TABLE, WorldState


def _make_gather_envelope(
    spawn_id: str,
    item: str,
    quantity: int,
    from_agent: str = "farmer-01",
) -> Envelope:
    """Helper to build GATHER envelopes for testing."""
    return Envelope(
        **{"from": from_agent},
        topic="/world/nature",
        tick=1,
        type=MessageType.GATHER,
        payload={"spawn_id": spawn_id, "item": item, "quantity": quantity},
    )


class TestProcessTick:
    def test_advances_tick(self):
        state = WorldState()
        tick, spawn_id, items = process_tick(state)
        assert tick == 1
        assert state.current_tick == 1

    def test_creates_spawn_pool(self):
        state = WorldState()
        tick, spawn_id, items = process_tick(state)
        assert spawn_id  # non-empty
        assert items == DEFAULT_SPAWN_TABLE

    def test_consecutive_ticks(self):
        state = WorldState()
        t1, s1, _ = process_tick(state)
        t2, s2, _ = process_tick(state)
        assert t1 == 1
        assert t2 == 2
        assert s1 != s2

    def test_replaces_previous_spawn(self):
        state = WorldState()
        _, s1, _ = process_tick(state)
        _, s2, _ = process_tick(state)
        # Active spawn should be the latest
        assert state.active_spawn is not None
        assert state.active_spawn.spawn_id == s2


class TestProcessGather:
    def _state_with_spawn(self) -> tuple[WorldState, str]:
        state = WorldState()
        _, spawn_id, _ = process_tick(state)
        return state, spawn_id

    def test_successful_gather(self):
        state, spawn_id = self._state_with_spawn()
        env = _make_gather_envelope(spawn_id, "potato", 5)
        granted, success, reason = process_gather(env, state)
        assert granted == 5
        assert success is True
        assert reason is None

    def test_partial_gather(self):
        state, spawn_id = self._state_with_spawn()
        env = _make_gather_envelope(spawn_id, "potato", 25)
        granted, success, reason = process_gather(env, state)
        assert granted == 20  # Default potato is 20
        assert success is True
        assert "Partial" in reason  # type: ignore[operator]

    def test_expired_spawn(self):
        state, spawn_id = self._state_with_spawn()
        # Advance to new tick (replaces spawn)
        process_tick(state)
        env = _make_gather_envelope(spawn_id, "potato", 5)
        granted, success, reason = process_gather(env, state)
        assert granted == 0
        assert success is False
        assert "expired" in reason.lower()  # type: ignore[union-attr]

    def test_missing_spawn_id(self):
        state, _ = self._state_with_spawn()
        env = Envelope(
            **{"from": "farmer-01"},
            topic="/world/nature",
            tick=1,
            type=MessageType.GATHER,
            payload={"spawn_id": "", "item": "potato", "quantity": 5},
        )
        granted, success, reason = process_gather(env, state)
        assert granted == 0
        assert success is False

    def test_missing_item(self):
        state, spawn_id = self._state_with_spawn()
        env = Envelope(
            **{"from": "farmer-01"},
            topic="/world/nature",
            tick=1,
            type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "", "quantity": 5},
        )
        granted, success, reason = process_gather(env, state)
        assert granted == 0
        assert success is False

    def test_zero_quantity(self):
        state, spawn_id = self._state_with_spawn()
        env = _make_gather_envelope(spawn_id, "potato", 0)
        # Override quantity to 0 (bypassing Pydantic validation on Gather model)
        env.payload["quantity"] = 0
        granted, success, reason = process_gather(env, state)
        assert granted == 0
        assert success is False

    def test_depleted_item(self):
        state, spawn_id = self._state_with_spawn()
        # First gather drains all potatoes
        env1 = _make_gather_envelope(spawn_id, "potato", 20)
        process_gather(env1, state)
        # Second gather fails
        env2 = _make_gather_envelope(spawn_id, "potato", 1, from_agent="farmer-02")
        granted, success, reason = process_gather(env2, state)
        assert granted == 0
        assert success is False
        assert "No potato remaining" in reason  # type: ignore[operator]

    def test_unknown_item(self):
        state, spawn_id = self._state_with_spawn()
        env = _make_gather_envelope(spawn_id, "diamond", 1)
        granted, success, reason = process_gather(env, state)
        assert granted == 0
        assert success is False

    def test_fcfs_ordering(self):
        state, spawn_id = self._state_with_spawn()
        # Stone has 10 in default table
        e1 = _make_gather_envelope(spawn_id, "stone", 7, from_agent="agent-1")
        e2 = _make_gather_envelope(spawn_id, "stone", 7, from_agent="agent-2")
        g1, s1, _ = process_gather(e1, state)
        g2, s2, r2 = process_gather(e2, state)
        assert g1 == 7
        assert s1 is True
        assert g2 == 3  # Only 3 left
        assert s2 is True
        assert "Partial" in r2  # type: ignore[operator]
