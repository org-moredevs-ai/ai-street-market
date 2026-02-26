"""Tests for the PolicyEngine — loads and parses YAML world/season configs.

These tests run against the REAL policy YAML files shipped in policies/.
No mocks. No NATS. Pure unit tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from streetmarket.policy.engine import (
    Award,
    CharacterConfig,
    PolicyEngine,
    RegionConfig,
    SeasonConfig,
    WinningCriterion,
    WorldPolicy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

POLICY_DIR = Path(__file__).parent.parent / "policies"


@pytest.fixture()
def engine() -> PolicyEngine:
    """Return a PolicyEngine pointing at the real policies/ directory."""
    return PolicyEngine(POLICY_DIR)


@pytest.fixture()
def season(engine: PolicyEngine) -> SeasonConfig:
    """Load the season-1 config."""
    return engine.load_season("season-1.yaml")


@pytest.fixture()
def world(engine: PolicyEngine) -> WorldPolicy:
    """Load the earth-medieval-temperate world policy."""
    return engine.load_world("earth-medieval-temperate.yaml")


# ---------------------------------------------------------------------------
# Season config tests
# ---------------------------------------------------------------------------


class TestLoadSeasonConfig:
    """Test loading season-1.yaml and verifying top-level fields."""

    def test_load_season_config(self, season: SeasonConfig) -> None:
        assert season.name == "Harvest Festival"
        assert season.number == 1
        assert season.tick_interval_seconds == 10
        assert season.starts_at == datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert season.ends_at == datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
        assert season.world_policy_file == "earth-medieval-temperate.yaml"
        has_desc = (
            "Harvest Festival" in season.description or "first season" in season.description.lower()
        )
        assert has_desc

    def test_season_total_ticks(self, season: SeasonConfig) -> None:
        """7 days / 10s per tick = 60480 ticks."""
        assert season.total_ticks == 60480

    def test_season_closing_tick(self, season: SeasonConfig) -> None:
        """Closing starts at 80% of total ticks (closing_percent=20)."""
        assert season.closing_percent == 20
        assert season.closing_tick == 48384

    def test_season_duration_seconds(self, season: SeasonConfig) -> None:
        """7 days = 604800 seconds."""
        assert season.duration_seconds == 604_800.0


class TestSeasonWinningCriteria:
    """Verify winning criteria loaded from season-1.yaml."""

    def test_season_winning_criteria_count(self, season: SeasonConfig) -> None:
        assert len(season.winning_criteria) == 3

    def test_season_winning_criteria_types(self, season: SeasonConfig) -> None:
        for criterion in season.winning_criteria:
            assert isinstance(criterion, WinningCriterion)

    def test_season_winning_criteria_metrics(self, season: SeasonConfig) -> None:
        metrics = {c.metric for c in season.winning_criteria}
        assert metrics == {"net_worth", "survival_ticks", "community_contribution"}

    def test_season_winning_criteria_weights_sum_to_one(self, season: SeasonConfig) -> None:
        total = sum(c.weight for c in season.winning_criteria)
        assert total == pytest.approx(1.0)

    def test_season_winning_criteria_individual_weights(self, season: SeasonConfig) -> None:
        by_metric = {c.metric: c.weight for c in season.winning_criteria}
        assert by_metric["net_worth"] == pytest.approx(0.4)
        assert by_metric["survival_ticks"] == pytest.approx(0.3)
        assert by_metric["community_contribution"] == pytest.approx(0.3)

    def test_season_winning_criteria_have_descriptions(self, season: SeasonConfig) -> None:
        for criterion in season.winning_criteria:
            assert criterion.description, f"Missing description for {criterion.metric}"


class TestSeasonAwards:
    """Verify awards loaded from season-1.yaml."""

    def test_season_awards_count(self, season: SeasonConfig) -> None:
        assert len(season.awards) == 5

    def test_season_awards_types(self, season: SeasonConfig) -> None:
        for award in season.awards:
            assert isinstance(award, Award)

    def test_season_awards_names(self, season: SeasonConfig) -> None:
        names = {a.name for a in season.awards}
        expected = {
            "Market Champion",
            "Wealthiest Trader",
            "Last One Standing",
            "Community Pillar",
            "Newcomer of the Season",
        }
        assert names == expected

    def test_season_awards_have_criteria(self, season: SeasonConfig) -> None:
        for award in season.awards:
            assert award.criteria, f"Missing criteria for {award.name}"

    def test_season_awards_have_descriptions(self, season: SeasonConfig) -> None:
        for award in season.awards:
            assert award.description, f"Missing description for {award.name}"


class TestSeasonCharacters:
    """Verify character configs loaded from season-1.yaml."""

    EXPECTED_ROLES = {"governor", "nature", "meteo", "town_crier", "landlord", "banker"}

    def test_season_characters_all_present(self, season: SeasonConfig) -> None:
        assert set(season.characters.keys()) == self.EXPECTED_ROLES

    def test_season_characters_types(self, season: SeasonConfig) -> None:
        for role, char in season.characters.items():
            assert isinstance(char, CharacterConfig), f"{role} is not a CharacterConfig"

    def test_season_characters_have_names(self, season: SeasonConfig) -> None:
        expected_names = {
            "governor": "Magistrate Aldric",
            "nature": "The Harvest Spirit",
            "meteo": "Old Weathervane Wes",
            "town_crier": "Herald Bellsworth",
            "landlord": "Lady Thornberry",
            "banker": "Clerk Pennyworth",
        }
        for role, expected_name in expected_names.items():
            assert season.characters[role].character == expected_name, (
                f"Character name mismatch for {role}"
            )

    def test_season_characters_have_personality(self, season: SeasonConfig) -> None:
        for role, char in season.characters.items():
            assert char.personality, f"Missing personality for {role}"


# ---------------------------------------------------------------------------
# World policy tests
# ---------------------------------------------------------------------------


class TestLoadWorldPolicy:
    """Test loading earth-medieval-temperate.yaml and verifying top-level fields."""

    def test_load_world_policy(self, world: WorldPolicy) -> None:
        assert world.name == "Medieval Market Town"
        assert world.era == "medieval"
        assert world.climate == "temperate"
        assert "market town" in world.description.lower()

    def test_world_regions_count(self, world: WorldPolicy) -> None:
        assert len(world.regions) == 6

    def test_world_regions_types(self, world: WorldPolicy) -> None:
        for region in world.regions:
            assert isinstance(region, RegionConfig)

    def test_world_regions_names_and_types(self, world: WorldPolicy) -> None:
        expected = {
            "Town Square": "market",
            "Eastern Farmland": "farmland",
            "Northern Forest": "forest",
            "Eastern Quarry": "quarry",
            "Western River": "water",
            "Southern Pastures": "pasture",
        }
        actual = {r.name: r.type for r in world.regions}
        assert actual == expected

    def test_world_regions_have_descriptions(self, world: WorldPolicy) -> None:
        for region in world.regions:
            assert region.description, f"Missing description for {region.name}"

    def test_world_resources_exist(self, world: WorldPolicy) -> None:
        assert "crops" in world.resources
        assert "gathered" in world.resources
        assert "animals" in world.resources

    def test_world_resources_crops_not_empty(self, world: WorldPolicy) -> None:
        assert len(world.resources["crops"]) > 0

    def test_world_resources_gathered_not_empty(self, world: WorldPolicy) -> None:
        assert len(world.resources["gathered"]) > 0

    def test_world_resources_animals_not_empty(self, world: WorldPolicy) -> None:
        assert len(world.resources["animals"]) > 0

    def test_world_raw_text(self, world: WorldPolicy) -> None:
        text = world.raw_text
        assert isinstance(text, str)
        assert len(text) > 0
        assert "Medieval Market Town" in text
        assert "medieval" in text.lower()
        assert "temperate" in text.lower()
        # Should contain region names
        assert "Town Square" in text
        assert "Northern Forest" in text

    def test_world_has_crafting(self, world: WorldPolicy) -> None:
        assert world.crafting, "Missing crafting config"

    def test_world_has_energy(self, world: WorldPolicy) -> None:
        assert world.energy, "Missing energy config"

    def test_world_has_economy(self, world: WorldPolicy) -> None:
        assert world.economy, "Missing economy config"

    def test_world_has_weather(self, world: WorldPolicy) -> None:
        assert world.weather, "Missing weather config"

    def test_world_has_social(self, world: WorldPolicy) -> None:
        assert world.social, "Missing social config"


# ---------------------------------------------------------------------------
# Integration: load world from season
# ---------------------------------------------------------------------------


class TestLoadWorldFromSeason:
    """Load the season, then use its world_policy_file to load the world."""

    def test_load_world_from_season(self, engine: PolicyEngine, season: SeasonConfig) -> None:
        world = engine.load_world(season.world_policy_file)
        assert isinstance(world, WorldPolicy)
        assert world.name == "Medieval Market Town"
        assert world.era == "medieval"
        assert world.climate == "temperate"
        assert len(world.regions) == 6
