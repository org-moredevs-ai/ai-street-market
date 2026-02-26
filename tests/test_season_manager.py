"""Tests for SeasonManager — UTC-based season lifecycle management."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.season.manager import SeasonManager, SeasonPhase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def season_config() -> SeasonConfig:
    """A 10-minute season with 10s ticks = 60 total ticks, 20% closing."""
    return SeasonConfig(
        name="Test Season",
        number=1,
        description="test",
        starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 15, 10, 10, 0, tzinfo=timezone.utc),
        tick_interval_seconds=10,
        world_policy_file="test.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[WinningCriterion(metric="net_worth", weight=1.0)],
        awards=[],
        closing_percent=20,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


@pytest.fixture
def manager(season_config: SeasonConfig) -> SeasonManager:
    """Fresh season manager in ANNOUNCED phase."""
    return SeasonManager(season_config)


# ===========================================================================
# CONFIG PROPERTY TESTS
# ===========================================================================


class TestSeasonConfigProperties:
    """Verify computed properties on SeasonConfig itself."""

    def test_total_ticks(self, season_config: SeasonConfig) -> None:
        # 10 minutes = 600 seconds / 10 seconds per tick = 60 ticks
        assert season_config.total_ticks == 60

    def test_duration_seconds(self, season_config: SeasonConfig) -> None:
        assert season_config.duration_seconds == 600.0

    def test_closing_tick(self, season_config: SeasonConfig) -> None:
        # closing_percent = 20 => closing_tick = 60 * (100 - 20) / 100 = 48
        assert season_config.closing_tick == 48


# ===========================================================================
# INITIAL STATE TESTS
# ===========================================================================


class TestInitialState:
    """Verify manager starts in the correct initial state."""

    def test_initial_phase_is_announced(self, manager: SeasonManager) -> None:
        assert manager.phase == SeasonPhase.ANNOUNCED

    def test_initial_tick_is_zero(self, manager: SeasonManager) -> None:
        assert manager.current_tick == 0

    def test_total_ticks_matches_config(self, manager: SeasonManager) -> None:
        assert manager.total_ticks == 60

    def test_config_accessible(self, manager: SeasonManager) -> None:
        assert manager.config.name == "Test Season"
        assert manager.config.number == 1

    def test_initial_progress_is_zero(self, manager: SeasonManager) -> None:
        assert manager.progress_percent == 0.0

    def test_not_accepting_agents_initially(self, manager: SeasonManager) -> None:
        assert manager.is_accepting_agents is False

    def test_not_running_initially(self, manager: SeasonManager) -> None:
        assert manager.is_running is False


# ===========================================================================
# PHASE TRANSITION TESTS
# ===========================================================================


class TestPhaseTransitions:
    """Tests for manual phase advancement via advance_to()."""

    def test_advance_to_preparation(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.PREPARATION)
        assert manager.phase == SeasonPhase.PREPARATION

    def test_advance_to_open(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.PREPARATION)
        manager.advance_to(SeasonPhase.OPEN)
        assert manager.phase == SeasonPhase.OPEN

    def test_advance_to_closing(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        manager.advance_to(SeasonPhase.CLOSING)
        assert manager.phase == SeasonPhase.CLOSING

    def test_advance_to_ended(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        manager.advance_to(SeasonPhase.ENDED)
        assert manager.phase == SeasonPhase.ENDED

    def test_advance_directly_to_open(self, manager: SeasonManager) -> None:
        """advance_to does not enforce ordering; it just sets the phase."""
        manager.advance_to(SeasonPhase.OPEN)
        assert manager.phase == SeasonPhase.OPEN


# ===========================================================================
# ACCEPTING AGENTS TESTS
# ===========================================================================


class TestAcceptingAgents:
    """Tests for is_accepting_agents property."""

    def test_not_accepting_in_announced(self, manager: SeasonManager) -> None:
        assert manager.is_accepting_agents is False

    def test_not_accepting_in_preparation(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.PREPARATION)
        assert manager.is_accepting_agents is False

    def test_accepting_in_open(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        assert manager.is_accepting_agents is True

    def test_not_accepting_in_closing(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.CLOSING)
        assert manager.is_accepting_agents is False

    def test_not_accepting_in_ended(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.ENDED)
        assert manager.is_accepting_agents is False


# ===========================================================================
# IS_RUNNING TESTS
# ===========================================================================


class TestIsRunning:
    """Tests for is_running property."""

    def test_not_running_in_announced(self, manager: SeasonManager) -> None:
        assert manager.is_running is False

    def test_not_running_in_preparation(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.PREPARATION)
        assert manager.is_running is False

    def test_running_in_open(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        assert manager.is_running is True

    def test_running_in_closing(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.CLOSING)
        assert manager.is_running is True

    def test_not_running_in_ended(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.ENDED)
        assert manager.is_running is False


# ===========================================================================
# TICK TESTS
# ===========================================================================


class TestTick:
    """Tests for the tick() method."""

    def test_tick_advances_count(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        result = manager.tick()
        assert result == 1
        assert manager.current_tick == 1

    def test_multiple_ticks(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for i in range(1, 11):
            result = manager.tick()
            assert result == i
        assert manager.current_tick == 10

    def test_tick_raises_when_announced(self, manager: SeasonManager) -> None:
        with pytest.raises(RuntimeError, match="Cannot tick in phase announced"):
            manager.tick()

    def test_tick_raises_when_preparation(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.PREPARATION)
        with pytest.raises(RuntimeError, match="Cannot tick in phase preparation"):
            manager.tick()

    def test_tick_raises_when_ended(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.ENDED)
        with pytest.raises(RuntimeError, match="Cannot tick in phase ended"):
            manager.tick()

    def test_tick_works_in_closing(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.CLOSING)
        result = manager.tick()
        assert result == 1

    def test_tick_returns_new_tick_number(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        assert manager.tick() == 1
        assert manager.tick() == 2
        assert manager.tick() == 3


# ===========================================================================
# AUTO-TRANSITION TESTS
# ===========================================================================


class TestAutoTransitions:
    """Tests for automatic phase transitions triggered by tick()."""

    def test_auto_transition_to_closing_at_80_percent(self, manager: SeasonManager) -> None:
        """At closing_percent=20, closing_tick=48. Reaching tick 48 triggers CLOSING."""
        manager.advance_to(SeasonPhase.OPEN)

        # Tick up to 47 — should still be OPEN
        for _ in range(47):
            manager.tick()
        assert manager.phase == SeasonPhase.OPEN
        assert manager.current_tick == 47

        # Tick 48 triggers transition to CLOSING
        manager.tick()
        assert manager.current_tick == 48
        assert manager.phase == SeasonPhase.CLOSING

    def test_remains_closing_between_48_and_59(self, manager: SeasonManager) -> None:
        """After transition to CLOSING, stays there until total_ticks."""
        manager.advance_to(SeasonPhase.OPEN)

        # Advance to tick 48 (triggers CLOSING)
        for _ in range(48):
            manager.tick()
        assert manager.phase == SeasonPhase.CLOSING

        # Ticks 49-59 should remain CLOSING
        for _ in range(11):
            manager.tick()
        assert manager.current_tick == 59
        assert manager.phase == SeasonPhase.CLOSING

    def test_auto_transition_to_ended_at_100_percent(self, manager: SeasonManager) -> None:
        """Reaching tick 60 (total_ticks) triggers ENDED."""
        manager.advance_to(SeasonPhase.OPEN)

        # Advance to 59
        for _ in range(59):
            manager.tick()
        assert manager.phase == SeasonPhase.CLOSING  # Should have transitioned at 48
        assert manager.current_tick == 59

        # Tick 60 triggers ENDED
        manager.tick()
        assert manager.current_tick == 60
        assert manager.phase == SeasonPhase.ENDED

    def test_full_lifecycle_through_ticks(self, manager: SeasonManager) -> None:
        """Run all 60 ticks and verify the full phase lifecycle."""
        manager.advance_to(SeasonPhase.OPEN)

        phases_seen: list[str] = []
        for _ in range(60):
            manager.tick()
            if not phases_seen or phases_seen[-1] != manager.phase.value:
                phases_seen.append(manager.phase.value)

        assert phases_seen == ["open", "closing", "ended"]
        assert manager.current_tick == 60
        assert manager.phase == SeasonPhase.ENDED

    def test_cannot_tick_after_ended(self, manager: SeasonManager) -> None:
        """After auto-transition to ENDED, ticking raises RuntimeError."""
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(60):
            manager.tick()
        assert manager.phase == SeasonPhase.ENDED

        with pytest.raises(RuntimeError, match="Cannot tick in phase ended"):
            manager.tick()


# ===========================================================================
# PROGRESS TESTS
# ===========================================================================


class TestProgress:
    """Tests for progress_percent property."""

    def test_progress_at_zero(self, manager: SeasonManager) -> None:
        assert manager.progress_percent == 0.0

    def test_progress_at_half(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(30):
            manager.tick()
        assert manager.progress_percent == 50.0

    def test_progress_at_full(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(60):
            manager.tick()
        assert manager.progress_percent == 100.0

    def test_progress_capped_at_100(self, season_config: SeasonConfig) -> None:
        """progress_percent should never exceed 100 even if tick exceeds total."""
        mgr = SeasonManager(season_config)
        mgr.advance_to(SeasonPhase.OPEN)
        # Manually set tick beyond total to test cap
        mgr._state.current_tick = 999
        assert mgr.progress_percent == 100.0

    def test_progress_at_closing_threshold(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(48):
            manager.tick()
        assert manager.progress_percent == 80.0

    def test_progress_with_zero_total_ticks(self) -> None:
        """A season with zero duration should report 0% progress."""
        config = SeasonConfig(
            name="Zero Season",
            number=99,
            description="instant",
            starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
            tick_interval_seconds=10,
            world_policy_file="test.yaml",
            biases={},
            agent_defaults={},
            winning_criteria=[],
            awards=[],
            closing_percent=20,
            preparation_hours=1,
            next_season_hint="",
            characters={},
        )
        mgr = SeasonManager(config)
        assert mgr.progress_percent == 0.0


# ===========================================================================
# TIME CONVERSION TESTS
# ===========================================================================


class TestTimeConversion:
    """Tests for tick_to_utc and utc_to_tick conversions."""

    def test_tick_to_utc_tick_zero(self, manager: SeasonManager) -> None:
        result = manager.tick_to_utc(0)
        assert result == datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_tick_to_utc_tick_one(self, manager: SeasonManager) -> None:
        result = manager.tick_to_utc(1)
        expected = datetime(2026, 3, 15, 10, 0, 10, tzinfo=timezone.utc)
        assert result == expected

    def test_tick_to_utc_tick_60(self, manager: SeasonManager) -> None:
        result = manager.tick_to_utc(60)
        expected = datetime(2026, 3, 15, 10, 10, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_tick_to_utc_mid_season(self, manager: SeasonManager) -> None:
        # Tick 30 = 300 seconds = 5 minutes after start
        result = manager.tick_to_utc(30)
        expected = datetime(2026, 3, 15, 10, 5, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_utc_to_tick_at_start(self, manager: SeasonManager) -> None:
        dt = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert manager.utc_to_tick(dt) == 0

    def test_utc_to_tick_at_end(self, manager: SeasonManager) -> None:
        dt = datetime(2026, 3, 15, 10, 10, 0, tzinfo=timezone.utc)
        assert manager.utc_to_tick(dt) == 60

    def test_utc_to_tick_mid_interval(self, manager: SeasonManager) -> None:
        # 15 seconds after start = between tick 1 and tick 2, should floor to 1
        dt = datetime(2026, 3, 15, 10, 0, 15, tzinfo=timezone.utc)
        assert manager.utc_to_tick(dt) == 1

    def test_utc_to_tick_before_start_clamps_to_zero(self, manager: SeasonManager) -> None:
        dt = datetime(2026, 3, 15, 9, 0, 0, tzinfo=timezone.utc)
        assert manager.utc_to_tick(dt) == 0

    def test_roundtrip_tick_utc_tick(self, manager: SeasonManager) -> None:
        """tick -> utc -> tick should be identity for exact boundaries."""
        for tick in [0, 1, 10, 30, 48, 59, 60]:
            utc = manager.tick_to_utc(tick)
            assert manager.utc_to_tick(utc) == tick


# ===========================================================================
# SNAPSHOT TESTS
# ===========================================================================


class TestSnapshot:
    """Tests for the snapshot() method."""

    def test_snapshot_initial(self, manager: SeasonManager) -> None:
        snap = manager.snapshot()
        assert snap["name"] == "Test Season"
        assert snap["number"] == 1
        assert snap["phase"] == "announced"
        assert snap["current_tick"] == 0
        assert snap["total_ticks"] == 60
        assert snap["progress_percent"] == 0.0
        assert snap["tick_interval_seconds"] == 10
        assert snap["starts_at"] == "2026-03-15T10:00:00+00:00"
        assert snap["ends_at"] == "2026-03-15T10:10:00+00:00"

    def test_snapshot_during_open(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(10):
            manager.tick()

        snap = manager.snapshot()
        assert snap["phase"] == "open"
        assert snap["current_tick"] == 10
        assert snap["progress_percent"] == round(10 / 60 * 100, 1)

    def test_snapshot_during_closing(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(48):
            manager.tick()

        snap = manager.snapshot()
        assert snap["phase"] == "closing"
        assert snap["current_tick"] == 48
        assert snap["progress_percent"] == 80.0

    def test_snapshot_at_end(self, manager: SeasonManager) -> None:
        manager.advance_to(SeasonPhase.OPEN)
        for _ in range(60):
            manager.tick()

        snap = manager.snapshot()
        assert snap["phase"] == "ended"
        assert snap["current_tick"] == 60
        assert snap["progress_percent"] == 100.0

    def test_snapshot_keys(self, manager: SeasonManager) -> None:
        """Verify snapshot contains exactly the expected keys."""
        expected_keys = {
            "name",
            "number",
            "phase",
            "current_tick",
            "total_ticks",
            "progress_percent",
            "tick_interval_seconds",
            "starts_at",
            "ends_at",
        }
        assert set(manager.snapshot().keys()) == expected_keys


# ===========================================================================
# SEASON PHASE ENUM TESTS
# ===========================================================================


class TestSeasonPhaseEnum:
    """Verify SeasonPhase enum values."""

    def test_phase_values(self) -> None:
        assert SeasonPhase.DORMANT.value == "dormant"
        assert SeasonPhase.ANNOUNCED.value == "announced"
        assert SeasonPhase.PREPARATION.value == "preparation"
        assert SeasonPhase.OPEN.value == "open"
        assert SeasonPhase.CLOSING.value == "closing"
        assert SeasonPhase.ENDED.value == "ended"

    def test_phase_count(self) -> None:
        assert len(SeasonPhase) == 6
