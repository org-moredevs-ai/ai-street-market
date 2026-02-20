"""Unit tests for World Engine state."""

from services.world.state import DEFAULT_SPAWN_TABLE, WorldState


class TestTickAdvancement:
    def test_starts_at_zero(self):
        state = WorldState()
        assert state.current_tick == 0

    def test_advance_increments(self):
        state = WorldState()
        assert state.advance_tick() == 1
        assert state.advance_tick() == 2
        assert state.current_tick == 2

    def test_advance_returns_new_tick(self):
        state = WorldState()
        result = state.advance_tick()
        assert result == state.current_tick


class TestSpawnCreation:
    def test_no_spawn_initially(self):
        state = WorldState()
        assert state.active_spawn is None

    def test_create_spawn_uses_default_table(self):
        state = WorldState()
        state.advance_tick()
        pool = state.create_spawn()
        assert pool.tick == 1
        assert pool.remaining == DEFAULT_SPAWN_TABLE

    def test_create_spawn_replaces_previous(self):
        state = WorldState()
        state.advance_tick()
        pool1 = state.create_spawn()
        state.advance_tick()
        pool2 = state.create_spawn()
        assert pool1.spawn_id != pool2.spawn_id
        assert state.active_spawn is pool2

    def test_spawn_id_is_unique(self):
        state = WorldState()
        ids = set()
        for _ in range(10):
            state.advance_tick()
            pool = state.create_spawn()
            ids.add(pool.spawn_id)
        assert len(ids) == 10

    def test_custom_spawn_table(self):
        custom = {"gold": 5, "diamond": 1}
        state = WorldState(_spawn_table=custom)
        state.advance_tick()
        pool = state.create_spawn()
        assert pool.remaining == {"gold": 5, "diamond": 1}


class TestTryGather:
    def _state_with_spawn(self) -> WorldState:
        state = WorldState()
        state.advance_tick()
        state.create_spawn()
        return state

    def test_no_active_spawn(self):
        state = WorldState()
        granted, error = state.try_gather("fake-id", "potato", 5)
        assert granted == 0
        assert error == "No active spawn"

    def test_wrong_spawn_id(self):
        state = self._state_with_spawn()
        granted, error = state.try_gather("wrong-id", "potato", 5)
        assert granted == 0
        assert error == "Spawn expired or not found"

    def test_successful_gather(self):
        state = self._state_with_spawn()
        spawn_id = state.active_spawn.spawn_id  # type: ignore[union-attr]
        granted, error = state.try_gather(spawn_id, "potato", 5)
        assert granted == 5
        assert error is None
        assert state.active_spawn.remaining["potato"] == 15  # type: ignore[union-attr]

    def test_partial_grant(self):
        state = self._state_with_spawn()
        spawn_id = state.active_spawn.spawn_id  # type: ignore[union-attr]
        # Request more than available (potato has 20)
        granted, error = state.try_gather(spawn_id, "potato", 25)
        assert granted == 20
        assert error is None
        assert state.active_spawn.remaining["potato"] == 0  # type: ignore[union-attr]

    def test_depleted_item(self):
        state = self._state_with_spawn()
        spawn_id = state.active_spawn.spawn_id  # type: ignore[union-attr]
        # Drain all potatoes
        state.try_gather(spawn_id, "potato", 20)
        # Try again
        granted, error = state.try_gather(spawn_id, "potato", 1)
        assert granted == 0
        assert error == "No potato remaining in spawn"

    def test_unknown_item(self):
        state = self._state_with_spawn()
        spawn_id = state.active_spawn.spawn_id  # type: ignore[union-attr]
        granted, error = state.try_gather(spawn_id, "gold", 5)
        assert granted == 0
        assert error == "No gold remaining in spawn"

    def test_multiple_gathers_fcfs(self):
        state = self._state_with_spawn()
        spawn_id = state.active_spawn.spawn_id  # type: ignore[union-attr]
        # First agent takes 15
        g1, _ = state.try_gather(spawn_id, "potato", 15)
        assert g1 == 15
        # Second agent asks for 10 but only 5 left
        g2, _ = state.try_gather(spawn_id, "potato", 10)
        assert g2 == 5
        # Third agent gets nothing
        g3, err = state.try_gather(spawn_id, "potato", 1)
        assert g3 == 0
        assert "No potato remaining" in err  # type: ignore[operator]
