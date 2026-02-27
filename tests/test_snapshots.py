"""Tests for state snapshot serialization and restore."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.persistence.snapshots import StateSnapshot
from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.ranking.engine import RankingEngine
from streetmarket.registry.registry import (
    AgentRegistry,
    AgentState,
    DeathInfo,
    Profile,
)
from streetmarket.season.manager import SeasonManager, SeasonPhase
from streetmarket.world_state.store import (
    Building,
    Field,
    FieldStatus,
    Resource,
    Weather,
    WeatherEffect,
    WorldStateStore,
)


def _make_season_config() -> SeasonConfig:
    return SeasonConfig(
        name="Test Season",
        number=1,
        description="A test season",
        starts_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        tick_interval_seconds=60,
        world_policy_file="earth-medieval-temperate.yaml",
        biases={},
        agent_defaults={"initial_balance": 100},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.5),
            WinningCriterion(metric="survival_ticks", weight=0.3),
            WinningCriterion(metric="community_contribution", weight=0.2),
        ],
        awards=[],
        closing_percent=20,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


def _make_infra() -> tuple[
    InMemoryLedger, AgentRegistry, WorldStateStore, SeasonManager, RankingEngine
]:
    config = _make_season_config()
    ledger = InMemoryLedger()
    registry = AgentRegistry()
    world_state = WorldStateStore()
    season_manager = SeasonManager(config)
    ranking_engine = RankingEngine(config, ledger, registry)
    return ledger, registry, world_state, season_manager, ranking_engine


async def _populate_state(
    ledger: InMemoryLedger,
    registry: AgentRegistry,
    world_state: WorldStateStore,
    season_manager: SeasonManager,
    ranking_engine: RankingEngine,
) -> None:
    """Populate all infrastructure with test data."""
    # Ledger: wallets + inventory + transactions
    await ledger.create_wallet("baker-alice", Decimal("150.50"))
    await ledger.credit("baker-alice", Decimal("20"), "sold bread", tick=5)
    await ledger.add_item("baker-alice", "bread", 10, tick=3)
    await ledger.add_item("baker-alice", "flour", 5, tick=1)
    await ledger.remove_item("baker-alice", "bread", 3)

    await ledger.create_wallet("farmer-bob", Decimal("80"))
    await ledger.add_item("farmer-bob", "wheat", 20, tick=2)

    # Registry: agents with different states
    await registry.register(
        "baker-alice",
        owner="alice",
        display_name="Alice the Baker",
        tick=1,
        profile=Profile(
            description="A talented baker",
            capabilities=["baking", "trading"],
            objectives="Become the best baker",
        ),
        energy=85.0,
    )

    await registry.register(
        "farmer-bob",
        owner="bob",
        display_name="Bob the Farmer",
        tick=2,
        profile=Profile(description="A wheat farmer", capabilities=["farming"], objectives=""),
    )
    await registry.set_state(
        "farmer-bob",
        AgentState.INACTIVE,
        death=DeathInfo(reason="bankruptcy", tick=10, final_message="Goodbye!", final_score=42.5),
    )

    # World state
    await world_state.add_field(
        Field(
            id="field-1",
            type="farmland",
            location="north meadow",
            status=FieldStatus.GROWING,
            crop="wheat",
            planted_tick=3,
            ready_tick=10,
            quantity_available=0,
            owner="farmer-bob",
            conditions={"soil": "rich"},
        )
    )
    await world_state.add_field(Field(id="field-2", type="forest", location="eastern woods"))

    await world_state.add_building(
        Building(
            id="bakery-1",
            type="bakery",
            owner="baker-alice",
            location="town center",
            built_tick=2,
            condition="good",
            features=["oven", "counter"],
            occupants=["baker-alice"],
        )
    )

    await world_state.add_resource(
        Resource(
            id="stone-quarry",
            type="stone",
            location="western hills",
            quantity=100,
            replenish_rate=5,
            conditions={"hardness": 0.8},
        )
    )

    await world_state.set_weather(
        Weather(
            condition="rainy",
            temperature="cool",
            wind="moderate",
            started_tick=5,
            effects=[
                WeatherEffect(
                    type="crop_boost",
                    target="wheat",
                    modifier=1.2,
                    until_tick=15,
                    reason="rain helps wheat",
                )
            ],
            forecast=[{"tick": 20, "condition": "sunny"}],
        )
    )

    await world_state.set_property("prop-1", {"owner": "baker-alice", "type": "shop", "rent": 10})

    # Season: advance to OPEN + tick
    season_manager.advance_to(SeasonPhase.PREPARATION)
    season_manager.advance_to(SeasonPhase.OPEN)
    for _ in range(10):
        season_manager.tick()

    # Ranking: community scores
    ranking_engine.record_community_contribution("baker-alice", 15.0)
    ranking_engine.record_community_contribution("farmer-bob", 5.0)


class TestStateSnapshotSaveRestore:
    """Test save and restore round-trip."""

    async def test_save_creates_file(self, tmp_path: Path) -> None:
        ledger, registry, world_state, season, ranking = _make_infra()
        await _populate_state(ledger, registry, world_state, season, ranking)

        filepath = StateSnapshot.save(
            tmp_path,
            tick=10,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season,
            ranking_engine=ranking,
        )

        assert filepath.exists()
        assert filepath.name == "snapshot-tick-10.json"

        data = json.loads(filepath.read_text())
        assert data["version"] == 1
        assert data["tick"] == 10
        assert "ledger" in data
        assert "registry" in data
        assert "world_state" in data
        assert "season" in data
        assert "ranking" in data

    async def test_full_round_trip(self, tmp_path: Path) -> None:
        """Save populated state, restore to fresh infra, verify equality."""
        ledger, registry, world_state, season, ranking = _make_infra()
        await _populate_state(ledger, registry, world_state, season, ranking)

        # Save
        StateSnapshot.save(
            tmp_path,
            tick=10,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season,
            ranking_engine=ranking,
        )

        # Create fresh infrastructure
        ledger2, registry2, world_state2, season2, ranking2 = _make_infra()

        # Restore
        snapshot_file = StateSnapshot.find_latest(tmp_path)
        assert snapshot_file is not None
        state = StateSnapshot.restore(snapshot_file)
        restored_tick = StateSnapshot.apply(
            state,
            ledger=ledger2,
            registry=registry2,
            world_state=world_state2,
            season_manager=season2,
            ranking_engine=ranking2,
        )

        assert restored_tick == 10

        # Verify ledger
        w1 = ledger._wallets["baker-alice"]
        w2 = ledger2._wallets["baker-alice"]
        assert w2.balance == w1.balance
        assert w2.total_earned == w1.total_earned
        assert w2.total_spent == w1.total_spent

        # baker-alice should have 7 bread (10 - 3) and 5 flour
        inv1 = await ledger.get_inventory("baker-alice")
        inv2 = await ledger2.get_inventory("baker-alice")
        assert inv2 == inv1

        # farmer-bob wallet
        w_bob1 = ledger._wallets["farmer-bob"]
        w_bob2 = ledger2._wallets["farmer-bob"]
        assert w_bob2.balance == w_bob1.balance

        # Transactions preserved
        txn1 = await ledger.get_transactions("baker-alice")
        txn2 = await ledger2.get_transactions("baker-alice")
        assert len(txn2) == len(txn1)

        # Verify registry
        alice1 = registry._agents["baker-alice"]
        alice2 = registry2._agents["baker-alice"]
        assert alice2.display_name == alice1.display_name
        assert alice2.state == alice1.state
        assert alice2.energy == alice1.energy
        assert alice2.profile.description == alice1.profile.description
        assert alice2.profile.capabilities == alice1.profile.capabilities

        bob2 = registry2._agents["farmer-bob"]
        assert bob2.state == AgentState.INACTIVE
        assert bob2.death is not None
        assert bob2.death.reason == "bankruptcy"
        assert bob2.death.tick == 10
        assert bob2.death.final_score == 42.5

        # Verify world state
        f1 = world_state._fields["field-1"]
        f2 = world_state2._fields["field-1"]
        assert f2.type == f1.type
        assert f2.status == FieldStatus.GROWING
        assert f2.crop == "wheat"
        assert f2.owner == "farmer-bob"
        assert f2.conditions == {"soil": "rich"}

        assert "field-2" in world_state2._fields

        b2 = world_state2._buildings["bakery-1"]
        assert b2.type == "bakery"
        assert b2.owner == "baker-alice"
        assert b2.features == ["oven", "counter"]

        r2 = world_state2._resources["stone-quarry"]
        assert r2.type == "stone"
        assert r2.quantity == 100

        w = world_state2._weather
        assert w.condition == "rainy"
        assert w.temperature == "cool"
        assert w.wind == "moderate"
        assert len(w.effects) == 1
        assert w.effects[0].type == "crop_boost"
        assert w.effects[0].modifier == 1.2

        props = world_state2._properties
        assert "prop-1" in props
        assert props["prop-1"]["owner"] == "baker-alice"

        # Verify season
        assert season2.phase == SeasonPhase.OPEN
        assert season2.current_tick == 10

        # Verify ranking
        assert ranking2._community_scores["baker-alice"] == 15.0
        assert ranking2._community_scores["farmer-bob"] == 5.0

    async def test_find_latest_no_snapshots(self, tmp_path: Path) -> None:
        assert StateSnapshot.find_latest(tmp_path) is None

    async def test_find_latest_nonexistent_dir(self) -> None:
        assert StateSnapshot.find_latest("/nonexistent/path") is None

    async def test_find_latest_picks_highest_tick(self, tmp_path: Path) -> None:
        ledger, registry, world_state, season, ranking = _make_infra()

        # Save multiple snapshots
        for tick in [5, 15, 10]:
            StateSnapshot.save(
                tmp_path,
                tick=tick,
                ledger=ledger,
                registry=registry,
                world_state=world_state,
                season_manager=season,
                ranking_engine=ranking,
            )

        latest = StateSnapshot.find_latest(tmp_path)
        assert latest is not None
        assert "tick-15" in latest.name

    async def test_cleanup_keeps_max_snapshots(self, tmp_path: Path) -> None:
        ledger, registry, world_state, season, ranking = _make_infra()

        for tick in range(1, 7):
            StateSnapshot.save(
                tmp_path,
                tick=tick,
                ledger=ledger,
                registry=registry,
                world_state=world_state,
                season_manager=season,
                ranking_engine=ranking,
            )

        # Should only keep last 3
        snapshots = list(tmp_path.glob("snapshot-tick-*.json"))
        assert len(snapshots) == 3
        names = sorted(s.name for s in snapshots)
        assert "snapshot-tick-4.json" in names
        assert "snapshot-tick-5.json" in names
        assert "snapshot-tick-6.json" in names

    async def test_empty_state_round_trip(self, tmp_path: Path) -> None:
        """Save and restore completely empty state."""
        ledger, registry, world_state, season, ranking = _make_infra()

        StateSnapshot.save(
            tmp_path,
            tick=0,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season,
            ranking_engine=ranking,
        )

        ledger2, registry2, world_state2, season2, ranking2 = _make_infra()
        state = StateSnapshot.restore(tmp_path / "snapshot-tick-0.json")
        StateSnapshot.apply(
            state,
            ledger=ledger2,
            registry=registry2,
            world_state=world_state2,
            season_manager=season2,
            ranking_engine=ranking2,
        )

        assert len(ledger2._wallets) == 0
        assert len(registry2._agents) == 0
        assert len(world_state2._fields) == 0

    async def test_decimal_precision_preserved(self, tmp_path: Path) -> None:
        """Ensure Decimal values survive JSON round-trip."""
        ledger, registry, world_state, season, ranking = _make_infra()
        await ledger.create_wallet("test-agent", Decimal("123.456789"))

        StateSnapshot.save(
            tmp_path,
            tick=1,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season,
            ranking_engine=ranking,
        )

        ledger2, registry2, world_state2, season2, ranking2 = _make_infra()
        state = StateSnapshot.restore(tmp_path / "snapshot-tick-1.json")
        StateSnapshot.apply(
            state,
            ledger=ledger2,
            registry=registry2,
            world_state=world_state2,
            season_manager=season2,
            ranking_engine=ranking2,
        )

        w = ledger2._wallets["test-agent"]
        assert w.balance == Decimal("123.456789")

    async def test_season_phase_closing(self, tmp_path: Path) -> None:
        """Ensure CLOSING phase is preserved."""
        ledger, registry, world_state, season, ranking = _make_infra()
        season.advance_to(SeasonPhase.PREPARATION)
        season.advance_to(SeasonPhase.OPEN)
        # Tick enough times to enter CLOSING
        while season.phase != SeasonPhase.CLOSING:
            season.tick()

        tick = season.current_tick

        StateSnapshot.save(
            tmp_path,
            tick=tick,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season,
            ranking_engine=ranking,
        )

        ledger2, registry2, world_state2, season2, ranking2 = _make_infra()
        state = StateSnapshot.restore(tmp_path / f"snapshot-tick-{tick}.json")
        StateSnapshot.apply(
            state,
            ledger=ledger2,
            registry=registry2,
            world_state=world_state2,
            season_manager=season2,
            ranking_engine=ranking2,
        )

        assert season2.phase == SeasonPhase.CLOSING
        assert season2.current_tick == tick
