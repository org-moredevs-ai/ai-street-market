"""Tests for the Agent LLM Brain — all LLM calls are mocked."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from streetmarket.agent.actions import ActionKind
from streetmarket.agent.llm_brain import (
    MARKET_RULES,
    VALID_KINDS,
    ActionPlan,
    AgentAction,
    AgentLLMBrain,
    serialize_state,
    validate_action,
    validate_plan,
)
from streetmarket.agent.llm_config import LLMConfig
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GATHER_PARAMS = {
    "spawn_id": "spawn-abc", "item": "potato", "quantity": 5,
}


def _gather_action() -> AgentAction:
    return AgentAction(kind="gather", params=_GATHER_PARAMS)


def _offer_action(qty: int = 3, price: float = 2.4) -> AgentAction:
    return AgentAction(
        kind="offer",
        params={"item": "potato", "quantity": qty, "price_per_unit": price},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_state() -> AgentState:
    """A basic agent state for testing."""
    state = AgentState(agent_id="farmer-01")
    state.wallet = 100.0
    state.energy = 80.0
    state.current_tick = 10
    state.inventory = {"potato": 5, "onion": 3}
    state.current_spawn_id = "spawn-abc"
    state.current_spawn_items = {"potato": 10, "onion": 5, "wood": 8}
    return state


@pytest.fixture
def state_with_offers(basic_state: AgentState) -> AgentState:
    """State with observed offers."""
    basic_state.observed_offers = [
        ObservedOffer(
            msg_id="msg-001",
            from_agent="chef-01",
            item="potato",
            quantity=3,
            price_per_unit=2.5,
            is_sell=False,  # chef wants to BUY
        ),
        ObservedOffer(
            msg_id="msg-002",
            from_agent="lumberjack-01",
            item="wood",
            quantity=5,
            price_per_unit=3.6,
            is_sell=True,  # lumberjack is SELLING
        ),
    ]
    return basic_state


@pytest.fixture
def env_vars():
    """Set required environment variables for LLM config."""
    env = {
        "OPENROUTER_API_KEY": "sk-or-test-key",
        "DEFAULT_MODEL": "test-model",
        "DEFAULT_MAX_TOKENS": "400",
        "DEFAULT_TEMPERATURE": "0.7",
    }
    with patch.dict(os.environ, env, clear=False):
        yield env


# ---------------------------------------------------------------------------
# LLMConfig tests
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_for_agent_loads_env(self, env_vars):
        config = LLMConfig.for_agent("farmer-01")
        assert config.api_key == "sk-or-test-key"
        assert config.model == "test-model"
        assert config.max_tokens == 400
        assert config.temperature == 0.7
        assert "openrouter" in config.api_base

    def test_for_agent_uses_per_agent_model(self, env_vars):
        with patch.dict(os.environ, {"FARMER_MODEL": "custom-model"}):
            config = LLMConfig.for_agent("farmer-01")
            assert config.model == "custom-model"

    def test_for_agent_per_agent_max_tokens(self, env_vars):
        with patch.dict(os.environ, {"FARMER_MAX_TOKENS": "200"}):
            config = LLMConfig.for_agent("farmer-01")
            assert config.max_tokens == 200

    def test_for_agent_per_agent_temperature(self, env_vars):
        with patch.dict(os.environ, {"FARMER_TEMPERATURE": "0.3"}):
            config = LLMConfig.for_agent("farmer-01")
            assert config.temperature == 0.3

    def test_for_agent_raises_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                LLMConfig.for_agent("farmer-01")

    def test_for_agent_raises_on_empty_model(self):
        env = {"OPENROUTER_API_KEY": "sk-or-test"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="LLM model is empty"):
                LLMConfig.for_agent("farmer-01")

    def test_for_service_loads_env(self, env_vars):
        config = LLMConfig.for_service("town_crier")
        assert config.api_key == "sk-or-test-key"
        assert config.model == "test-model"

    def test_for_service_per_service_model(self, env_vars):
        with patch.dict(os.environ, {"TOWN_CRIER_MODEL": "narrator-model"}):
            config = LLMConfig.for_service("town_crier")
            assert config.model == "narrator-model"


# ---------------------------------------------------------------------------
# Serialize state tests
# ---------------------------------------------------------------------------


class TestSerializeState:
    def test_basic_serialization(self, basic_state):
        text = serialize_state(basic_state)
        assert "Tick: 10" in text
        assert "Wallet: 100.0" in text
        assert "Energy: 80/100" in text
        assert "potato: 5" in text
        assert "onion: 3" in text
        assert "spawn-abc" in text

    def test_empty_inventory(self):
        state = AgentState(agent_id="test-01")
        text = serialize_state(state)
        assert "Inventory: empty" in text

    def test_no_spawn(self):
        state = AgentState(agent_id="test-01")
        text = serialize_state(state)
        assert "Nature spawn: none this tick" in text

    def test_crafting_state(self, basic_state):
        basic_state.active_craft = CraftingJob(
            recipe="soup", started_tick=8, duration_ticks=2
        )
        text = serialize_state(basic_state)
        assert "Crafting: soup" in text
        assert "0 ticks remaining" in text

    def test_observed_offers(self, state_with_offers):
        text = serialize_state(state_with_offers)
        assert "chef-01" in text
        assert "BUYING" in text
        assert "msg-001" in text
        assert "lumberjack-01" in text
        assert "SELLING" in text

    def test_bankrupt_state(self, basic_state):
        basic_state.is_bankrupt = True
        text = serialize_state(basic_state)
        assert "BANKRUPT" in text

    def test_rent_shown(self, basic_state):
        basic_state.rent_due_this_tick = 2.0
        text = serialize_state(basic_state)
        assert "Rent deducted" in text
        assert "2.0" in text


# ---------------------------------------------------------------------------
# Validate action tests
# ---------------------------------------------------------------------------


class TestValidateAction:
    def test_valid_gather(self, basic_state):
        action = AgentAction(
            kind="gather",
            params={"spawn_id": "spawn-abc", "item": "potato", "quantity": 5},
        )
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.kind == ActionKind.GATHER
        assert result.params["quantity"] == 5

    def test_gather_clamps_quantity(self, basic_state):
        action = AgentAction(
            kind="gather",
            params={"spawn_id": "spawn-abc", "item": "potato", "quantity": 100},
        )
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.params["quantity"] == 10  # clamped to available

    def test_gather_invalid_item(self, basic_state):
        action = AgentAction(
            kind="gather",
            params={"spawn_id": "spawn-abc", "item": "diamond", "quantity": 1},
        )
        result = validate_action(action, basic_state)
        assert result is None

    def test_gather_no_spawn(self):
        state = AgentState(agent_id="test-01")
        action = AgentAction(
            kind="gather",
            params={"item": "potato", "quantity": 1},
        )
        result = validate_action(action, state)
        assert result is None

    def test_valid_offer(self, basic_state):
        action = AgentAction(
            kind="offer",
            params={"item": "potato", "quantity": 3, "price_per_unit": 2.4},
        )
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.kind == ActionKind.OFFER

    def test_offer_insufficient_inventory(self, basic_state):
        action = AgentAction(
            kind="offer",
            params={"item": "potato", "quantity": 100, "price_per_unit": 2.0},
        )
        result = validate_action(action, basic_state)
        assert result is None

    def test_offer_invalid_item(self, basic_state):
        action = AgentAction(
            kind="offer",
            params={"item": "diamond", "quantity": 1, "price_per_unit": 100.0},
        )
        result = validate_action(action, basic_state)
        assert result is None

    def test_valid_bid(self, basic_state):
        action = AgentAction(
            kind="bid",
            params={"item": "wood", "quantity": 3, "max_price_per_unit": 4.0},
        )
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.kind == ActionKind.BID

    def test_bid_invalid_item(self, basic_state):
        action = AgentAction(
            kind="bid",
            params={"item": "diamond", "quantity": 1, "max_price_per_unit": 1.0},
        )
        result = validate_action(action, basic_state)
        assert result is None

    def test_valid_accept(self, state_with_offers):
        action = AgentAction(
            kind="accept",
            params={
                "reference_msg_id": "msg-001",
                "quantity": 3,
                "topic": "/market/raw-goods",
            },
        )
        result = validate_action(action, state_with_offers)
        assert result is not None
        assert result.kind == ActionKind.ACCEPT

    def test_accept_unknown_msg_id(self, state_with_offers):
        action = AgentAction(
            kind="accept",
            params={
                "reference_msg_id": "msg-999",
                "quantity": 1,
                "topic": "/market/raw-goods",
            },
        )
        result = validate_action(action, state_with_offers)
        assert result is None

    def test_valid_craft_start(self, basic_state):
        basic_state.inventory = {"potato": 5, "onion": 3}
        action = AgentAction(kind="craft_start", params={"recipe": "soup"})
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.kind == ActionKind.CRAFT_START

    def test_craft_start_missing_ingredients(self, basic_state):
        basic_state.inventory = {"potato": 1}
        action = AgentAction(kind="craft_start", params={"recipe": "soup"})
        result = validate_action(action, basic_state)
        assert result is None

    def test_craft_start_already_crafting(self, basic_state):
        basic_state.active_craft = CraftingJob(
            recipe="soup", started_tick=8, duration_ticks=2
        )
        action = AgentAction(kind="craft_start", params={"recipe": "bread"})
        result = validate_action(action, basic_state)
        assert result is None

    def test_craft_start_invalid_recipe(self, basic_state):
        action = AgentAction(kind="craft_start", params={"recipe": "pizza"})
        result = validate_action(action, basic_state)
        assert result is None

    def test_valid_consume_soup(self, basic_state):
        basic_state.inventory["soup"] = 1
        action = AgentAction(kind="consume", params={"item": "soup"})
        result = validate_action(action, basic_state)
        assert result is not None
        assert result.kind == ActionKind.CONSUME

    def test_consume_non_food(self, basic_state):
        action = AgentAction(kind="consume", params={"item": "potato"})
        result = validate_action(action, basic_state)
        assert result is None

    def test_consume_no_food_in_inventory(self, basic_state):
        action = AgentAction(kind="consume", params={"item": "soup"})
        result = validate_action(action, basic_state)
        assert result is None

    def test_invalid_kind(self, basic_state):
        action = AgentAction(kind="teleport", params={})
        result = validate_action(action, basic_state)
        assert result is None

    def test_low_energy_blocks_gather(self):
        state = AgentState(agent_id="test-01")
        state.energy = 5.0
        state.current_spawn_id = "spawn-1"
        state.current_spawn_items = {"potato": 10}
        action = AgentAction(
            kind="gather",
            params={"spawn_id": "spawn-1", "item": "potato", "quantity": 1},
        )
        result = validate_action(action, state)
        assert result is None


# ---------------------------------------------------------------------------
# Validate plan tests
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_filters_invalid_actions(self, basic_state):
        gather = _gather_action()
        offer = _offer_action(qty=2)
        plan = ActionPlan(
            reasoning="test",
            actions=[
                gather,
                AgentAction(kind="teleport", params={}),
                offer,
            ],
        )
        actions = validate_plan(plan, basic_state)
        assert len(actions) == 2
        assert actions[0].kind == ActionKind.GATHER
        assert actions[1].kind == ActionKind.OFFER

    def test_respects_action_budget(self, basic_state):
        basic_state.actions_this_tick = 4  # only 1 remaining
        plan = ActionPlan(
            reasoning="test",
            actions=[_gather_action(), _offer_action(qty=2)],
        )
        actions = validate_plan(plan, basic_state)
        assert len(actions) == 1

    def test_empty_plan(self, basic_state):
        plan = ActionPlan(reasoning="nothing to do", actions=[])
        actions = validate_plan(plan, basic_state)
        assert len(actions) == 0

    def test_cumulative_energy_tracking(self, basic_state):
        """Multiple gathers should be capped by cumulative energy, not just per-action."""
        basic_state.energy = 25.0  # enough for 2 gathers (10 each), not 3
        plan = ActionPlan(
            reasoning="gather everything",
            actions=[
                _gather_action(),
                _gather_action(),
                _gather_action(),  # should be skipped — energy exhausted
            ],
        )
        actions = validate_plan(plan, basic_state)
        assert len(actions) == 2

    def test_cumulative_energy_free_actions_pass(self, basic_state):
        """Free actions (consume) should not be blocked by energy tracking."""
        basic_state.energy = 5.0  # not enough for gather
        basic_state.inventory["soup"] = 2
        plan = ActionPlan(
            reasoning="eat soup",
            actions=[
                AgentAction(kind="consume", params={"item": "soup"}),
                AgentAction(kind="consume", params={"item": "soup"}),
            ],
        )
        actions = validate_plan(plan, basic_state)
        assert len(actions) == 2


# ---------------------------------------------------------------------------
# AgentLLMBrain tests
# ---------------------------------------------------------------------------


class TestAgentLLMBrain:
    @pytest.fixture
    def brain(self):
        return AgentLLMBrain("farmer-01", "You are Farmer Joe.")

    def _inject_mock(self, brain, mock_plan=None, side_effect=None):
        """Inject a mock structured client into the brain's cache."""
        if side_effect:
            mock_ainvoke = AsyncMock(side_effect=side_effect)
        else:
            mock_ainvoke = AsyncMock(return_value=mock_plan)
        brain._structured = MagicMock(ainvoke=mock_ainvoke)

    async def test_decide_calls_llm_and_returns_actions(
        self, brain, basic_state, env_vars,
    ):
        plan = ActionPlan(
            reasoning="Gathering potatoes this tick",
            actions=[_gather_action()],
        )
        self._inject_mock(brain, mock_plan=plan)

        actions = await brain.decide(basic_state)
        assert len(actions) == 1
        assert actions[0].kind == ActionKind.GATHER

    async def test_decide_returns_empty_on_llm_error(
        self, brain, basic_state, env_vars,
    ):
        self._inject_mock(brain, side_effect=Exception("API timeout"))

        actions = await brain.decide(basic_state)
        assert actions == []

    async def test_decide_returns_empty_on_config_error(
        self, brain, basic_state,
    ):
        # No OPENROUTER_API_KEY set — _get_structured raises
        with patch.dict(os.environ, {}, clear=True):
            actions = await brain.decide(basic_state)
        assert actions == []

    async def test_decide_validates_llm_output(
        self, brain, basic_state, env_vars,
    ):
        plan = ActionPlan(
            reasoning="Let's do impossible things",
            actions=[
                AgentAction(kind="teleport", params={}),
                AgentAction(kind="consume", params={"item": "diamond"}),
                _gather_action(),
            ],
        )
        self._inject_mock(brain, mock_plan=plan)

        actions = await brain.decide(basic_state)
        assert len(actions) == 1
        assert actions[0].kind == ActionKind.GATHER

    async def test_decide_multiple_valid_actions(
        self, brain, basic_state, env_vars,
    ):
        plan = ActionPlan(
            reasoning="Gather and sell",
            actions=[_gather_action(), _offer_action()],
        )
        self._inject_mock(brain, mock_plan=plan)

        actions = await brain.decide(basic_state)
        assert len(actions) == 2

    async def test_decide_empty_plan(self, brain, basic_state, env_vars):
        plan = ActionPlan(reasoning="Nothing useful to do", actions=[])
        self._inject_mock(brain, mock_plan=plan)

        actions = await brain.decide(basic_state)
        assert actions == []

    async def test_client_cached_across_calls(
        self, brain, basic_state, env_vars,
    ):
        """The LLM client should be created once and reused."""
        plan = ActionPlan(reasoning="test", actions=[])
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = MagicMock(
            ainvoke=AsyncMock(return_value=plan),
        )

        with patch(
            "streetmarket.agent.llm_brain.ChatOpenAI", return_value=mock_llm,
        ) as mock_cls:
            await brain.decide(basic_state)
            await brain.decide(basic_state)

        # ChatOpenAI constructor called only once (cached)
        assert mock_cls.call_count == 1


# ---------------------------------------------------------------------------
# Market rules prompt tests
# ---------------------------------------------------------------------------


class TestMarketRules:
    def test_market_rules_contains_key_info(self):
        assert "gather" in MARKET_RULES
        assert "offer" in MARKET_RULES
        assert "bid" in MARKET_RULES
        assert "accept" in MARKET_RULES
        assert "craft_start" in MARKET_RULES
        assert "consume" in MARKET_RULES
        assert "potato" in MARKET_RULES
        assert "soup" in MARKET_RULES
        assert "house" in MARKET_RULES
        assert "energy" in MARKET_RULES.lower()

    def test_valid_kinds_complete(self):
        assert VALID_KINDS == {"gather", "offer", "bid", "accept", "craft_start", "consume"}


# ---------------------------------------------------------------------------
# ActionPlan/AgentAction schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_action_plan_creation(self):
        plan = ActionPlan(
            reasoning="test plan",
            actions=[AgentAction(kind="gather", params={"item": "potato"})],
        )
        assert plan.reasoning == "test plan"
        assert len(plan.actions) == 1

    def test_action_plan_empty(self):
        plan = ActionPlan(reasoning="skip", actions=[])
        assert plan.actions == []

    def test_agent_action_creation(self):
        action = AgentAction(kind="offer", params={"item": "potato", "quantity": 5})
        assert action.kind == "offer"
        assert action.params["item"] == "potato"
