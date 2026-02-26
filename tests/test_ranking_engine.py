"""Tests for the ranking engine — season and overall rankings.

All tests are async (pytest-asyncio, asyncio_mode="auto").
No NATS needed — pure in-memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.ranking.engine import (
    OverallRankingEntry,
    RankingEngine,
    RankingEntry,
)
from streetmarket.registry.registry import (
    AgentRegistry,
    AgentState,
    DeathInfo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_season_config(number: int = 1) -> SeasonConfig:
    """Build a minimal SeasonConfig for tests."""
    return SeasonConfig(
        name="Test",
        number=number,
        description="test",
        starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 15, 11, 0, 0, tzinfo=timezone.utc),
        tick_interval_seconds=10,
        world_policy_file="test.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.4),
            WinningCriterion(metric="survival_ticks", weight=0.3),
            WinningCriterion(metric="community_contribution", weight=0.3),
        ],
        awards=[],
        closing_percent=20,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


@pytest.fixture
def season_config() -> SeasonConfig:
    return _make_season_config()


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def engine(
    season_config: SeasonConfig,
    ledger: InMemoryLedger,
    registry: AgentRegistry,
) -> RankingEngine:
    return RankingEngine(config=season_config, ledger=ledger, registry=registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_agent(
    registry: AgentRegistry,
    ledger: InMemoryLedger,
    agent_id: str,
    owner: str = "owner1",
    display_name: str | None = None,
    balance: Decimal = Decimal("10"),
    joined_tick: int = 0,
) -> None:
    """Register an agent in both registry and ledger."""
    await registry.register(
        agent_id=agent_id,
        owner=owner,
        display_name=display_name or agent_id.title(),
        tick=joined_tick,
    )
    await ledger.create_wallet(agent_id, initial_balance=balance)


# ---------------------------------------------------------------------------
# Tests — empty rankings
# ---------------------------------------------------------------------------


async def test_empty_rankings(engine: RankingEngine) -> None:
    """calculate_rankings returns an empty list when no agents are registered."""
    result = await engine.calculate_rankings(tick=10)
    assert result == []


# ---------------------------------------------------------------------------
# Tests — single agent ranking
# ---------------------------------------------------------------------------


async def test_single_agent_ranking(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """A single agent should get rank 1."""
    await _register_agent(registry, ledger, "farmer", owner="alice")

    rankings = await engine.calculate_rankings(tick=5)

    assert len(rankings) == 1
    entry = rankings[0]
    assert isinstance(entry, RankingEntry)
    assert entry.rank == 1
    assert entry.agent_id == "farmer"
    assert entry.owner == "alice"
    assert entry.state == AgentState.ACTIVE.value


# ---------------------------------------------------------------------------
# Tests — two agents ranked by score descending
# ---------------------------------------------------------------------------


async def test_two_agents_ranked_by_score_descending(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """The agent with a higher total score should be ranked first."""
    # Agent A: high wallet
    await _register_agent(registry, ledger, "agent_a", owner="alice", balance=Decimal("100"))
    # Agent B: low wallet
    await _register_agent(registry, ledger, "agent_b", owner="bob", balance=Decimal("5"))

    rankings = await engine.calculate_rankings(tick=10)

    assert len(rankings) == 2
    assert rankings[0].agent_id == "agent_a"
    assert rankings[0].rank == 1
    assert rankings[1].agent_id == "agent_b"
    assert rankings[1].rank == 2
    assert rankings[0].total_score > rankings[1].total_score


# ---------------------------------------------------------------------------
# Tests — net_worth includes wallet + inventory
# ---------------------------------------------------------------------------


async def test_net_worth_includes_wallet_and_inventory(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """net_worth score = wallet balance + inventory item count (1 coin each)."""
    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("20"))
    await ledger.add_item("farmer", "potato", 5, tick=1)
    await ledger.add_item("farmer", "onion", 3, tick=1)

    rankings = await engine.calculate_rankings(tick=10)

    entry = rankings[0]
    # Balance 20.0 + 8 items = 28.0
    assert entry.scores["net_worth"] == pytest.approx(28.0)


# ---------------------------------------------------------------------------
# Tests — survival_ticks for active vs dead agent
# ---------------------------------------------------------------------------


async def test_survival_ticks_active_agent(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """Active agent survival = current_tick - joined_tick."""
    await _register_agent(
        registry,
        ledger,
        "farmer",
        owner="alice",
        balance=Decimal("0"),
        joined_tick=5,
    )

    rankings = await engine.calculate_rankings(tick=25)

    entry = rankings[0]
    # 25 - 5 = 20 ticks survived
    assert entry.scores["survival_ticks"] == pytest.approx(20.0)


async def test_survival_ticks_dead_agent(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """Dead agent survival = death_tick - joined_tick."""
    await _register_agent(
        registry,
        ledger,
        "farmer",
        owner="alice",
        balance=Decimal("0"),
        joined_tick=5,
    )
    await registry.set_state(
        "farmer",
        AgentState.INACTIVE,
        death=DeathInfo(reason="bankruptcy", tick=15),
    )

    rankings = await engine.calculate_rankings(tick=50)

    entry = rankings[0]
    # 15 - 5 = 10 (capped at death tick)
    assert entry.scores["survival_ticks"] == pytest.approx(10.0)
    assert entry.death_reason == "bankruptcy"
    assert entry.state == AgentState.INACTIVE.value


# ---------------------------------------------------------------------------
# Tests — community contribution recording and scoring
# ---------------------------------------------------------------------------


async def test_community_contribution_recording(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """record_community_contribution accumulates points."""
    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("0"))

    engine.record_community_contribution("farmer", 10.0)
    engine.record_community_contribution("farmer", 5.0)

    rankings = await engine.calculate_rankings(tick=1)
    entry = rankings[0]
    assert entry.scores["community_contribution"] == pytest.approx(15.0)


async def test_community_contribution_default_zero(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """Agents without recorded contributions score 0.0."""
    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("0"))

    rankings = await engine.calculate_rankings(tick=1)
    entry = rankings[0]
    assert entry.scores["community_contribution"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests — weighted total calculation
# ---------------------------------------------------------------------------


async def test_weighted_total_calculation(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """Total = net_worth*0.4 + survival_ticks*0.3 + community*0.3."""
    await _register_agent(
        registry,
        ledger,
        "farmer",
        owner="alice",
        balance=Decimal("50"),
        joined_tick=0,
    )
    # Add inventory: 10 items -> net_worth = 50 + 10 = 60
    await ledger.add_item("farmer", "potato", 10, tick=1)
    # Community contribution: 20 points
    engine.record_community_contribution("farmer", 20.0)

    rankings = await engine.calculate_rankings(tick=30)
    entry = rankings[0]

    # net_worth = 60.0
    # survival_ticks = 30 - 0 = 30.0
    # community_contribution = 20.0
    expected = 60.0 * 0.4 + 30.0 * 0.3 + 20.0 * 0.3
    assert entry.total_score == pytest.approx(round(expected, 2))

    # Verify individual scores too
    assert entry.scores["net_worth"] == pytest.approx(60.0)
    assert entry.scores["survival_ticks"] == pytest.approx(30.0)
    assert entry.scores["community_contribution"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Tests — get_season_rankings returns stored results
# ---------------------------------------------------------------------------


async def test_get_season_rankings_empty_before_calculation(
    engine: RankingEngine,
) -> None:
    """Before any calculation, get_season_rankings returns empty list."""
    result = await engine.get_season_rankings(season=1)
    assert result == []


async def test_get_season_rankings_returns_stored_results(
    engine: RankingEngine,
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """After calculate_rankings, get_season_rankings returns the same data."""
    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("30"))
    await _register_agent(registry, ledger, "chef", owner="bob", balance=Decimal("10"))

    calculated = await engine.calculate_rankings(tick=20)
    stored = await engine.get_season_rankings(season=1)

    assert stored is calculated
    assert len(stored) == 2
    assert stored[0].rank == 1
    assert stored[1].rank == 2


async def test_get_season_rankings_nonexistent_season(
    engine: RankingEngine,
) -> None:
    """Querying a non-existent season returns empty list."""
    result = await engine.get_season_rankings(season=999)
    assert result == []


# ---------------------------------------------------------------------------
# Tests — get_overall_rankings across seasons
# ---------------------------------------------------------------------------


async def test_get_overall_rankings_empty(
    engine: RankingEngine,
) -> None:
    """No season data means empty overall rankings."""
    result = engine.get_overall_rankings()
    assert result == []


async def test_get_overall_rankings_single_season(
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """Overall rankings from a single season."""
    config = _make_season_config(number=1)
    engine = RankingEngine(config=config, ledger=ledger, registry=registry)

    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("50"))
    await _register_agent(registry, ledger, "chef", owner="bob", balance=Decimal("10"))

    await engine.calculate_rankings(tick=20)

    overall = engine.get_overall_rankings()
    assert len(overall) == 2
    assert all(isinstance(e, OverallRankingEntry) for e in overall)
    # Alice has higher net_worth -> higher total
    assert overall[0].owner == "alice"
    assert overall[0].rank == 1
    assert overall[1].owner == "bob"
    assert overall[1].rank == 2
    # Both played 1 season
    assert overall[0].seasons_played == 1
    assert overall[1].seasons_played == 1
    # Each deployed 1 agent
    assert overall[0].agents_deployed == 1
    assert overall[1].agents_deployed == 1


async def test_get_overall_rankings_tracks_wins(
    registry: AgentRegistry,
    ledger: InMemoryLedger,
) -> None:
    """The winner (rank 1) of a season gets a win counted."""
    config = _make_season_config(number=1)
    engine = RankingEngine(config=config, ledger=ledger, registry=registry)

    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("100"))
    await _register_agent(registry, ledger, "chef", owner="bob", balance=Decimal("5"))

    await engine.calculate_rankings(tick=10)

    overall = engine.get_overall_rankings()
    winner = next(e for e in overall if e.owner == "alice")
    loser = next(e for e in overall if e.owner == "bob")

    assert winner.wins == 1
    assert loser.wins == 0


async def test_get_overall_rankings_multiple_seasons(
    ledger: InMemoryLedger,
) -> None:
    """Overall rankings accumulate across multiple seasons.

    We simulate two seasons by manually storing rankings in history.
    """
    config = _make_season_config(number=1)
    registry = AgentRegistry()
    engine = RankingEngine(config=config, ledger=ledger, registry=registry)

    # -- Season 1 --
    await _register_agent(registry, ledger, "farmer", owner="alice", balance=Decimal("50"))
    await _register_agent(registry, ledger, "chef", owner="bob", balance=Decimal("30"))
    await engine.calculate_rankings(tick=20)

    # -- Season 2 (simulated by inserting directly into history) --
    season2_rankings = [
        RankingEntry(
            rank=1,
            agent_id="baker",
            owner="bob",
            scores={"net_worth": 80.0, "survival_ticks": 20.0, "community_contribution": 10.0},
            total_score=41.0,
            state="active",
        ),
        RankingEntry(
            rank=2,
            agent_id="mason",
            owner="alice",
            scores={"net_worth": 10.0, "survival_ticks": 20.0, "community_contribution": 0.0},
            total_score=10.0,
            state="active",
        ),
    ]
    engine._season_history[2] = season2_rankings

    overall = engine.get_overall_rankings()

    # Both owners have entries from both seasons
    alice = next(e for e in overall if e.owner == "alice")
    bob = next(e for e in overall if e.owner == "bob")

    assert alice.seasons_played == 2
    assert bob.seasons_played == 2
    assert alice.agents_deployed == 2  # farmer + mason
    assert bob.agents_deployed == 2  # chef + baker

    # Bob should have a win from season 2 (rank 1 = baker, owner bob)
    assert bob.wins >= 1
