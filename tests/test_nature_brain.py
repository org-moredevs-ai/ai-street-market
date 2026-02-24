"""Tests for NatureBrain — LLM Nature Intelligence (all mocked, no API key needed)."""

from unittest.mock import AsyncMock, MagicMock, patch

from services.world.nature import LLM_CALL_INTERVAL, NatureBrain, NatureEvent
from services.world.state import DEFAULT_SPAWN_TABLE

# ── Construction ────────────────────────────────────────────────────────────


class TestNatureBrainConstruction:
    @patch.dict("os.environ", {"WORLD_USE_LLM_NATURE": "false"}, clear=False)
    def test_disabled_by_default(self) -> None:
        brain = NatureBrain.__new__(NatureBrain)
        brain.enabled = False
        brain._cached_spawns = None
        brain._active_event = None
        brain._last_call_tick = 0
        brain._gather_history = []
        assert brain.enabled is False

    @patch.dict(
        "os.environ",
        {"WORLD_USE_LLM_NATURE": "true", "ANTHROPIC_API_KEY": "test-key"},
        clear=False,
    )
    def test_enabled_with_env_var_and_key(self) -> None:
        brain = NatureBrain()
        assert brain.enabled is True

    @patch.dict("os.environ", {"WORLD_USE_LLM_NATURE": "true"}, clear=False)
    def test_disabled_without_api_key(self) -> None:
        # Remove API key if present
        import os
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            brain = NatureBrain()
            assert brain.enabled is False
        finally:
            if old:
                os.environ["ANTHROPIC_API_KEY"] = old


# ── Gather history ──────────────────────────────────────────────────────────


class TestGatherHistory:
    def test_record_gather(self) -> None:
        brain = NatureBrain()
        brain.record_gather("farmer-01", "potato", 10, 1)
        assert len(brain.get_recent_gathers()) == 1

    def test_gather_history_capped_at_50(self) -> None:
        brain = NatureBrain()
        for i in range(60):
            brain.record_gather("agent", "potato", 1, i)
        assert len(brain.get_recent_gathers()) == 50

    def test_recent_gathers_returns_copy(self) -> None:
        brain = NatureBrain()
        brain.record_gather("a", "potato", 5, 1)
        gathers = brain.get_recent_gathers()
        gathers.clear()
        assert len(brain.get_recent_gathers()) == 1

    def test_gather_contains_correct_data(self) -> None:
        brain = NatureBrain()
        brain.record_gather("farmer-01", "potato", 10, 5)
        g = brain.get_recent_gathers()[0]
        assert g["agent"] == "farmer-01"
        assert g["item"] == "potato"
        assert g["quantity"] == 10
        assert g["tick"] == 5


# ── Should call LLM ────────────────────────────────────────────────────────


class TestShouldCallLLM:
    def test_disabled_never_calls(self) -> None:
        brain = NatureBrain()
        brain.enabled = False
        assert not brain.should_call_llm(100)

    def test_enabled_calls_at_interval(self) -> None:
        brain = NatureBrain()
        brain.enabled = True
        brain._last_call_tick = 0
        assert brain.should_call_llm(LLM_CALL_INTERVAL)

    def test_enabled_no_call_before_interval(self) -> None:
        brain = NatureBrain()
        brain.enabled = True
        brain._last_call_tick = 0
        assert not brain.should_call_llm(LLM_CALL_INTERVAL - 1)

    def test_calls_after_first_call(self) -> None:
        brain = NatureBrain()
        brain.enabled = True
        brain._last_call_tick = 5
        assert brain.should_call_llm(5 + LLM_CALL_INTERVAL)

    def test_no_call_immediately_after_previous(self) -> None:
        brain = NatureBrain()
        brain.enabled = True
        brain._last_call_tick = 5
        assert not brain.should_call_llm(6)


# ── Get spawn table ─────────────────────────────────────────────────────────


class TestGetSpawnTable:
    def test_returns_default_when_no_cache(self) -> None:
        brain = NatureBrain()
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        assert table == DEFAULT_SPAWN_TABLE

    def test_returns_cached_spawns(self) -> None:
        brain = NatureBrain()
        brain._cached_spawns = {"potato": 30, "onion": 10, "wood": 10, "nails": 5, "stone": 5}
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        assert table["potato"] == 30

    def test_returns_copy_not_reference(self) -> None:
        brain = NatureBrain()
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        table["potato"] = 999
        assert DEFAULT_SPAWN_TABLE["potato"] == 20

    def test_applies_event_effects_to_cached(self) -> None:
        brain = NatureBrain()
        brain._cached_spawns = {"potato": 20, "onion": 15, "wood": 15, "nails": 10, "stone": 10}
        brain._active_event = NatureEvent(
            event_id="test",
            title="Drought",
            description="",
            effects={"potato": 0.5},
            duration_ticks=5,
            remaining_ticks=3,
        )
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        assert table["potato"] == 10  # 20 * 0.5

    def test_event_effects_dont_go_negative(self) -> None:
        brain = NatureBrain()
        brain._cached_spawns = {"potato": 5, "onion": 15, "wood": 15, "nails": 10, "stone": 10}
        brain._active_event = NatureEvent(
            event_id="test",
            title="Blight",
            description="",
            effects={"potato": 0.0},
            duration_ticks=3,
            remaining_ticks=2,
        )
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        assert table["potato"] == 0

    def test_expired_event_not_applied(self) -> None:
        brain = NatureBrain()
        brain._cached_spawns = {"potato": 20, "onion": 15, "wood": 15, "nails": 10, "stone": 10}
        brain._active_event = NatureEvent(
            event_id="test",
            title="Expired",
            description="",
            effects={"potato": 0.5},
            duration_ticks=5,
            remaining_ticks=0,
        )
        table = brain.get_spawn_table(1, DEFAULT_SPAWN_TABLE)
        assert table["potato"] == 20  # No effect


# ── Tick event ──────────────────────────────────────────────────────────────


class TestTickEvent:
    def test_tick_event_decrements_remaining(self) -> None:
        brain = NatureBrain()
        brain._active_event = NatureEvent(
            event_id="test", title="Storm", description="",
            effects={}, duration_ticks=5, remaining_ticks=3,
        )
        result = brain.tick_event()
        assert result is not None
        assert result.remaining_ticks == 2

    def test_tick_event_clears_when_expired(self) -> None:
        brain = NatureBrain()
        brain._active_event = NatureEvent(
            event_id="test", title="Storm", description="",
            effects={}, duration_ticks=5, remaining_ticks=1,
        )
        result = brain.tick_event()
        assert result is None
        assert brain.active_event is None

    def test_tick_event_no_event_returns_none(self) -> None:
        brain = NatureBrain()
        assert brain.tick_event() is None


# ── Process LLM response ───────────────────────────────────────────────────


class TestProcessLLMResponse:
    def test_basic_spawn_response(self) -> None:
        brain = NatureBrain()
        result = brain._process_llm_response(
            {"spawns": {"potato": 25, "onion": 10, "wood": 20, "nails": 8, "stone": 12}},
            10,
        )
        assert result["potato"] == 25
        assert result["onion"] == 10
        assert brain._cached_spawns is not None

    def test_spawns_clamped_to_range(self) -> None:
        brain = NatureBrain()
        result = brain._process_llm_response(
            {"spawns": {"potato": 100, "onion": -5, "wood": 20, "nails": 8, "stone": 12}},
            10,
        )
        assert result["potato"] == 50  # Clamped to max
        assert result["onion"] == 0  # Clamped to min

    def test_missing_spawn_defaults_to_zero(self) -> None:
        brain = NatureBrain()
        result = brain._process_llm_response(
            {"spawns": {"potato": 10}},  # Missing others
            10,
        )
        assert result["onion"] == 0

    def test_event_created_from_response(self) -> None:
        brain = NatureBrain()
        brain._process_llm_response(
            {
                "spawns": {"potato": 10, "onion": 15, "wood": 15, "nails": 10, "stone": 10},
                "event": {
                    "title": "Potato Blight",
                    "description": "Potatoes are scarce",
                    "duration_ticks": 5,
                },
            },
            10,
        )
        assert brain.active_event is not None
        assert brain.active_event.title == "Potato Blight"
        assert brain.active_event.duration_ticks == 5
        assert brain.active_event.remaining_ticks == 5

    def test_event_duration_clamped(self) -> None:
        brain = NatureBrain()
        brain._process_llm_response(
            {
                "spawns": {"potato": 10, "onion": 15, "wood": 15, "nails": 10, "stone": 10},
                "event": {
                    "title": "Forever Storm",
                    "description": "Way too long",
                    "duration_ticks": 100,
                },
            },
            10,
        )
        assert brain.active_event is not None
        assert brain.active_event.duration_ticks == 15  # Clamped

    def test_event_not_replaced_if_active(self) -> None:
        brain = NatureBrain()
        brain._active_event = NatureEvent(
            event_id="existing", title="Old", description="",
            effects={}, duration_ticks=5, remaining_ticks=3,
        )
        brain._process_llm_response(
            {
                "spawns": {"potato": 10, "onion": 15, "wood": 15, "nails": 10, "stone": 10},
                "event": {"title": "New", "description": "", "duration_ticks": 5},
            },
            10,
        )
        assert brain.active_event.title == "Old"  # Not replaced


# ── Call LLM (mocked) ──────────────────────────────────────────────────────


class TestCallLLM:
    async def test_disabled_returns_default(self) -> None:
        brain = NatureBrain()
        brain.enabled = False
        result = await brain.call_llm(1, DEFAULT_SPAWN_TABLE, {})
        assert result == DEFAULT_SPAWN_TABLE

    async def test_llm_error_returns_default(self) -> None:
        brain = NatureBrain()
        brain.enabled = True

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))
        brain._client = mock_client

        result = await brain.call_llm(1, DEFAULT_SPAWN_TABLE, {})
        assert result == DEFAULT_SPAWN_TABLE

    async def test_successful_llm_call(self) -> None:
        brain = NatureBrain()
        brain.enabled = True

        # Mock the anthropic client
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "set_nature"
        mock_block.input = {
            "spawns": {"potato": 30, "onion": 20, "wood": 10, "nails": 10, "stone": 10},
        }

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        brain._client = mock_client

        result = await brain.call_llm(5, DEFAULT_SPAWN_TABLE, {"farmer": 80.0})

        assert result["potato"] == 30
        assert result["onion"] == 20

    async def test_llm_no_tool_use_returns_default(self) -> None:
        brain = NatureBrain()
        brain.enabled = True

        mock_block = MagicMock()
        mock_block.type = "text"

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        brain._client = mock_client

        result = await brain.call_llm(5, DEFAULT_SPAWN_TABLE, {})

        assert result == DEFAULT_SPAWN_TABLE

    async def test_llm_updates_last_call_tick(self) -> None:
        brain = NatureBrain()
        brain.enabled = True

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "set_nature"
        mock_block.input = {
            "spawns": {"potato": 20, "onion": 15, "wood": 15, "nails": 10, "stone": 10},
        }

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        brain._client = mock_client

        await brain.call_llm(10, DEFAULT_SPAWN_TABLE, {})

        assert brain._last_call_tick == 10


# ── Summarize gathers ──────────────────────────────────────────────────────


class TestSummarizeGathers:
    def test_empty_history(self) -> None:
        brain = NatureBrain()
        assert brain._summarize_gathers() == "No gather activity yet."

    def test_with_gathers(self) -> None:
        brain = NatureBrain()
        brain.record_gather("a", "potato", 10, 1)
        brain.record_gather("b", "potato", 5, 2)
        brain.record_gather("a", "wood", 8, 2)
        summary = brain._summarize_gathers()
        assert "potato: 15" in summary
        assert "wood: 8" in summary
