"""Tests for the Season Runner service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.season import SeasonPhase

from services.season_runner.runner import SeasonResult, SeasonRunner, SeasonRunnerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_season_config(
    *,
    name: str = "Test Season",
    number: int = 1,
    tick_interval: int = 1,
    duration_minutes: int = 1,
) -> SeasonConfig:
    """Create a short season config for testing."""
    start = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    # duration_minutes * 60 seconds / tick_interval = total ticks
    from datetime import timedelta

    end = start + timedelta(minutes=duration_minutes)
    return SeasonConfig(
        name=name,
        number=number,
        description="A test season",
        starts_at=start,
        ends_at=end,
        tick_interval_seconds=tick_interval,
        world_policy_file="test.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.5),
            WinningCriterion(metric="survival_ticks", weight=0.5),
        ],
        awards=[],
        closing_percent=20,
        preparation_hours=0,
        next_season_hint="",
        characters={},
    )


def _make_runner(season_config: SeasonConfig | None = None, **kwargs) -> SeasonRunner:
    """Create a runner without NATS connection."""
    config = SeasonRunnerConfig(
        season_config=season_config or _make_season_config(),
        nats_url="nats://localhost:4222",
        **kwargs,
    )
    return SeasonRunner(config)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_infrastructure(self):
        runner = _make_runner()
        assert runner.season is not None
        assert runner.registry is not None
        assert runner.ledger is not None
        assert runner.world_state is not None
        assert runner.ranking is not None

    def test_initial_state(self):
        runner = _make_runner()
        assert not runner.is_running
        assert runner.result is None
        assert runner.season.phase == SeasonPhase.ANNOUNCED

    def test_season_config_propagated(self):
        config = _make_season_config(name="Harvest Festival", number=3)
        runner = _make_runner(season_config=config)
        assert runner.season.config.name == "Harvest Festival"
        assert runner.season.config.number == 3


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------


class TestPhaseTransitions:
    async def test_prepare_transitions_to_preparation(self):
        runner = _make_runner()
        with patch(
            "services.season_runner.runner.MarketBusClient",
            return_value=AsyncMock(),
        ):
            await runner.prepare()
        assert runner.season.phase == SeasonPhase.PREPARATION

    async def test_open_transitions_to_open(self):
        runner = _make_runner()
        with patch(
            "services.season_runner.runner.MarketBusClient",
            return_value=AsyncMock(),
        ):
            await runner.prepare()
        await runner.open()
        assert runner.season.phase == SeasonPhase.OPEN
        assert runner._clock is not None

    async def test_finalize_transitions_to_ended(self):
        runner = _make_runner()
        # Manually advance to ended state
        runner._season.advance_to(SeasonPhase.OPEN)
        result = await runner.finalize()
        assert runner.season.phase == SeasonPhase.ENDED
        assert isinstance(result, SeasonResult)

    async def test_phase_change_callback_called(self):
        phases_seen: list[str] = []

        async def on_phase(phase_name: str, snapshot: dict) -> None:
            phases_seen.append(phase_name)

        runner = _make_runner(on_phase_change=on_phase)

        with patch(
            "services.season_runner.runner.MarketBusClient",
            return_value=AsyncMock(),
        ):
            await runner.prepare()
        await runner.open()

        assert "preparation" in phases_seen
        assert "open" in phases_seen


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    async def test_register_agent(self):
        runner = _make_runner()
        await runner.register_agent(
            agent_id="baker-hugo",
            owner="hugo",
            display_name="Hugo's Bakery",
        )
        agent = await runner.registry.get("baker-hugo")
        assert agent is not None
        assert agent.display_name == "Hugo's Bakery"

    async def test_register_creates_wallet(self):
        runner = _make_runner()
        await runner.register_agent(
            agent_id="baker-hugo",
            owner="hugo",
            display_name="Hugo's Bakery",
        )
        wallet = await runner.ledger.get_wallet("baker-hugo")
        assert wallet is not None
        assert float(wallet.balance) == 100.0

    async def test_register_multiple_agents(self):
        runner = _make_runner()
        for i in range(5):
            await runner.register_agent(
                agent_id=f"agent-{i}",
                owner=f"owner-{i}",
                display_name=f"Agent {i}",
            )
        agents = await runner.registry.list_agents()
        assert len(agents) == 5


# ---------------------------------------------------------------------------
# Season result
# ---------------------------------------------------------------------------


class TestSeasonResult:
    async def test_finalize_returns_result(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)

        # Register some agents
        await runner.register_agent("baker-1", "hugo", "Baker 1")
        await runner.register_agent("farmer-1", "maria", "Farmer 1")

        # Give baker more money (higher net worth)
        await runner.ledger.credit("baker-1", Decimal("200"), "test bonus")

        result = await runner.finalize()
        assert result.season_name == "Test Season"
        assert result.season_number == 1
        assert len(result.final_rankings) == 2

    async def test_winner_is_highest_scorer(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)

        await runner.register_agent("baker-1", "hugo", "Baker 1")
        await runner.register_agent("farmer-1", "maria", "Farmer 1")

        # Give baker much more money
        await runner.ledger.credit("baker-1", Decimal("500"), "test bonus")

        result = await runner.finalize()
        assert result.winner_agent_id == "baker-1"
        assert result.winner_owner == "hugo"

    async def test_empty_season_no_winner(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)
        result = await runner.finalize()
        assert result.winner_agent_id == ""
        assert result.winner_owner == ""
        assert result.final_rankings == []

    async def test_result_stored_on_runner(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)
        assert runner.result is None
        result = await runner.finalize()
        assert runner.result is result


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------


class TestRankings:
    async def test_rankings_sorted_by_score(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)

        # Create agents with different wealth
        agents = [
            ("agent-a", "owner-a", "Agent A", 50),
            ("agent-b", "owner-b", "Agent B", 300),
            ("agent-c", "owner-c", "Agent C", 150),
        ]
        for aid, owner, name, bonus in agents:
            await runner.register_agent(aid, owner, name)
            if bonus:
                await runner.ledger.credit(aid, Decimal(str(bonus)), "test bonus")

        result = await runner.finalize()
        assert result.final_rankings[0].agent_id == "agent-b"
        assert result.final_rankings[1].agent_id == "agent-c"
        assert result.final_rankings[2].agent_id == "agent-a"

    async def test_rankings_include_all_agents(self):
        runner = _make_runner()
        runner._season.advance_to(SeasonPhase.OPEN)

        for i in range(10):
            await runner.register_agent(f"agent-{i}", f"owner-{i}", f"Agent {i}")

        result = await runner.finalize()
        assert len(result.final_rankings) == 10

    async def test_overall_rankings_across_seasons(self):
        # Season 1
        config1 = _make_season_config(name="Season 1", number=1)
        runner1 = _make_runner(season_config=config1)
        runner1._season.advance_to(SeasonPhase.OPEN)
        await runner1.register_agent("baker-1", "hugo", "Baker")
        await runner1.ledger.credit("baker-1", Decimal("200"), "test bonus")
        await runner1.finalize()

        # The ranking engine has season 1 data
        overall = runner1.ranking.get_overall_rankings()
        assert len(overall) == 1
        assert overall[0].owner == "hugo"
        assert overall[0].wins == 1


# ---------------------------------------------------------------------------
# Stop and cleanup
# ---------------------------------------------------------------------------


class TestStopAndCleanup:
    async def test_stop_sets_running_false(self):
        runner = _make_runner()
        runner._running = True
        runner.stop()
        assert not runner.is_running

    async def test_cleanup_closes_nats(self):
        runner = _make_runner()
        runner._nats = AsyncMock()
        await runner._cleanup()
        runner._nats_before = None  # was set to None by cleanup
        assert runner._nats is None

    async def test_cleanup_stops_clock(self):
        runner = _make_runner()
        mock_clock = MagicMock()
        mock_clock.is_running = True
        runner._clock = mock_clock
        runner._nats = AsyncMock()
        await runner._cleanup()
        mock_clock.stop.assert_called_once()
