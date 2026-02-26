"""Tests for scripts/run_season.py — deployment wiring logic.

All tests mock LLM and NATS to avoid real connections.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.policy.engine import (
    Award,
    CharacterConfig,
    SeasonConfig,
    WinningCriterion,
    WorldPolicy,
)
from streetmarket.registry.registry import AgentRegistry
from streetmarket.world_state.store import WorldStateStore

from scripts.run_season import (
    create_market_agents,
    parse_args,
    validate_environment,
)
from services.banker.banker import BankerAgent
from services.governor.governor import GovernorAgent
from services.landlord.landlord import LandlordAgent
from services.meteo.meteo import MeteoAgent
from services.nature.nature import NatureAgent
from services.town_crier.narrator import TownCrierAgent

# -- Fixtures --


@pytest.fixture
def season_config() -> SeasonConfig:
    """Create a test season config with all 6 character configs."""
    return SeasonConfig(
        name="Test Season",
        number=1,
        description="A test season for unit tests",
        starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc),
        tick_interval_seconds=10,
        world_policy_file="earth-medieval-temperate.yaml",
        biases={},
        agent_defaults={"starting_wallet": 100, "energy": 100},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.4),
            WinningCriterion(metric="survival_ticks", weight=0.3),
        ],
        awards=[Award(name="Richest", criteria="highest_balance")],
        closing_percent=20,
        preparation_hours=24,
        next_season_hint="Winter is coming",
        characters={
            "governor": CharacterConfig(
                character="Magistrate Aldric",
                personality="Warm and welcoming but firm",
            ),
            "banker": CharacterConfig(
                character="Clerk Pennyworth",
                personality="Meticulous with dry humor",
            ),
            "nature": CharacterConfig(
                character="The Harvest Spirit",
                personality="Generous and nurturing",
            ),
            "meteo": CharacterConfig(
                character="Old Weathervane Wes",
                personality="Dramatic weather oracle",
            ),
            "landlord": CharacterConfig(
                character="Lady Thornberry",
                personality="Fair and business-minded",
            ),
            "town_crier": CharacterConfig(
                character="Herald Bellsworth",
                personality="Theatrical and loves underdog stories",
            ),
        },
    )


@pytest.fixture
def world_policy() -> WorldPolicy:
    """Create a test world policy."""
    return WorldPolicy(
        name="Test World",
        era="medieval",
        climate="temperate",
        description="A test world",
        regions=[],
        resources={},
        crafting={},
        energy={},
        economy={},
        weather={},
        social={},
    )


@pytest.fixture
def infrastructure() -> dict:
    """Create shared infrastructure instances."""
    return {
        "ledger": InMemoryLedger(),
        "registry": AgentRegistry(),
        "world_state": WorldStateStore(),
    }


@pytest.fixture
def mock_fns() -> dict:
    """Create mock publish and subscribe functions."""
    return {
        "publish_fn": AsyncMock(),
        "subscribe_fn": AsyncMock(),
    }


@pytest.fixture
def env_vars():
    """Set required environment variables for tests."""
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "test-key-123",
            "DEFAULT_MODEL": "test-model/v1",
        },
    ):
        yield


# -- Environment validation tests --


class TestValidateEnvironment:
    def test_missing_api_key(self):
        """Raises SystemExit when OPENROUTER_API_KEY is missing."""
        with patch.dict(os.environ, {"DEFAULT_MODEL": "test"}, clear=True):
            with pytest.raises(SystemExit):
                validate_environment()

    def test_missing_model(self):
        """Raises SystemExit when DEFAULT_MODEL is missing."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "key"}, clear=True):
            with pytest.raises(SystemExit):
                validate_environment()

    def test_missing_both(self):
        """Raises SystemExit when both are missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                validate_environment()

    def test_success(self):
        """Passes when both required vars are set."""
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-test", "DEFAULT_MODEL": "test/model"},
        ):
            validate_environment()  # Should not raise


# -- Agent creation tests --


class TestCreateMarketAgents:
    def test_creates_exactly_six_agents(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Creates exactly 6 market agents."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        assert len(agents) == 6

    def test_agent_types(self, season_config, world_policy, infrastructure, mock_fns, env_vars):
        """Creates the correct agent types in order."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        assert isinstance(agents[0], GovernorAgent)
        assert isinstance(agents[1], BankerAgent)
        assert isinstance(agents[2], NatureAgent)
        assert isinstance(agents[3], MeteoAgent)
        assert isinstance(agents[4], LandlordAgent)
        assert isinstance(agents[5], TownCrierAgent)

    def test_agents_get_character_names_from_yaml(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Agents get their character names from the season YAML config."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        assert agents[0].character_name == "Magistrate Aldric"
        assert agents[1].character_name == "Clerk Pennyworth"
        assert agents[2].character_name == "The Harvest Spirit"
        assert agents[3].character_name == "Old Weathervane Wes"
        assert agents[4].character_name == "Lady Thornberry"
        assert agents[5].character_name == "Herald Bellsworth"

    def test_agents_get_correct_ids(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Agents get the correct agent IDs."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        ids = [a.agent_id for a in agents]
        assert ids == ["governor", "banker", "nature", "meteo", "landlord", "town_crier"]

    def test_agents_get_correct_topics(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Each agent subscribes to the correct topics."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        # Governor: tick, square, trades
        gov_topics = agents[0].topics_to_subscribe()
        assert "/system/tick" in gov_topics
        assert "/market/square" in gov_topics
        assert "/market/trades" in gov_topics

        # Banker: tick, ledger, bank
        bank_topics = agents[1].topics_to_subscribe()
        assert "/system/tick" in bank_topics
        assert "/system/ledger" in bank_topics
        assert "/market/bank" in bank_topics

        # Nature: tick, ledger
        nature_topics = agents[2].topics_to_subscribe()
        assert "/system/tick" in nature_topics

        # Meteo: tick
        meteo_topics = agents[3].topics_to_subscribe()
        assert "/system/tick" in meteo_topics

        # Landlord: tick, property
        landlord_topics = agents[4].topics_to_subscribe()
        assert "/system/tick" in landlord_topics
        assert "/market/property" in landlord_topics

        # Town Crier: tick, square, trades, bank, weather, property, ledger
        crier_topics = agents[5].topics_to_subscribe()
        assert len(crier_topics) == 7

    def test_governor_gets_ledger_and_registry(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Governor is wired with ledger and registry."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        gov = agents[0]
        assert gov._ledger is infrastructure["ledger"]
        assert gov._registry is infrastructure["registry"]

    def test_banker_gets_ledger_and_registry(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Banker is wired with ledger and registry."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        banker = agents[1]
        assert banker._ledger is infrastructure["ledger"]
        assert banker._registry is infrastructure["registry"]

    def test_nature_gets_world_state(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Nature is wired with world state."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        nature = agents[2]
        assert nature._world_state is infrastructure["world_state"]

    def test_meteo_gets_world_state(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Meteo is wired with world state."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        meteo = agents[3]
        assert meteo._world_state is infrastructure["world_state"]

    def test_landlord_gets_all_three(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Landlord is wired with ledger, registry, and world state."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        landlord = agents[4]
        assert landlord._ledger is infrastructure["ledger"]
        assert landlord._registry is infrastructure["registry"]
        assert landlord._world_state is infrastructure["world_state"]

    def test_town_crier_gets_season_description(
        self, season_config, world_policy, infrastructure, mock_fns, env_vars
    ):
        """Town Crier is wired with the season description."""
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            **infrastructure,
            **mock_fns,
        )
        crier = agents[5]
        assert crier._season_description == "A test season for unit tests"


# -- Argument parsing tests --


class TestParseArgs:
    def test_defaults(self):
        """Default argument values are correct."""
        args = parse_args([])
        assert args.season == "season-1.yaml"
        assert args.policy_dir == "policies/"
        assert args.nats_url == "nats://localhost:4222"
        assert args.ws_port == 9090
        assert args.no_bridge is False
        assert args.tick_override is None

    def test_tick_override(self):
        """--tick-override sets the override value."""
        args = parse_args(["--tick-override", "2"])
        assert args.tick_override == 2

    def test_no_bridge(self):
        """--no-bridge flag works."""
        args = parse_args(["--no-bridge"])
        assert args.no_bridge is True

    def test_custom_season(self):
        """--season sets custom season file."""
        args = parse_args(["--season", "season-2.yaml"])
        assert args.season == "season-2.yaml"

    def test_custom_nats_url(self):
        """--nats-url sets custom NATS URL."""
        args = parse_args(["--nats-url", "nats://remote:4222"])
        assert args.nats_url == "nats://remote:4222"

    def test_custom_ws_port(self):
        """--ws-port sets custom WebSocket port."""
        args = parse_args(["--ws-port", "8080"])
        assert args.ws_port == 8080

    def test_custom_policy_dir(self):
        """--policy-dir sets custom policy directory."""
        args = parse_args(["--policy-dir", "/custom/policies"])
        assert args.policy_dir == "/custom/policies"
