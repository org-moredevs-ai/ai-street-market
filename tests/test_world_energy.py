"""Unit tests for World Engine energy system."""

from streetmarket.models.energy import (
    ACTION_ENERGY_COSTS,
    MAX_ENERGY,
    REGEN_PER_TICK,
    SHELTER_BONUS_REGEN,
    STARTING_ENERGY,
)

from services.world.rules import (
    apply_regen,
    check_gather_energy,
    deduct_gather_energy,
    get_energy_cost,
    process_consume_result,
)
from services.world.state import WorldState


def _make_state_with_agent(
    agent_id: str = "farmer-01", energy: float = STARTING_ENERGY,
) -> WorldState:
    """Create a WorldState with one registered agent."""
    state = WorldState()
    state.register_energy(agent_id)
    if energy != STARTING_ENERGY:
        state.set_energy(agent_id, energy)
    return state


class TestWorldStateEnergy:
    def test_register_energy_sets_starting(self):
        state = WorldState()
        state.register_energy("agent-1")
        assert state.get_energy("agent-1") == STARTING_ENERGY

    def test_register_energy_idempotent(self):
        state = WorldState()
        state.register_energy("agent-1")
        state.set_energy("agent-1", 50.0)
        state.register_energy("agent-1")  # Should not reset
        assert state.get_energy("agent-1") == 50.0

    def test_get_energy_unknown_agent(self):
        state = WorldState()
        assert state.get_energy("unknown") == 0.0

    def test_set_energy_clamped_to_max(self):
        state = _make_state_with_agent()
        state.set_energy("farmer-01", 200.0)
        assert state.get_energy("farmer-01") == MAX_ENERGY

    def test_set_energy_clamped_to_zero(self):
        state = _make_state_with_agent()
        state.set_energy("farmer-01", -10.0)
        assert state.get_energy("farmer-01") == 0.0

    def test_deduct_energy_success(self):
        state = _make_state_with_agent(energy=50.0)
        result = state.deduct_energy("farmer-01", 10.0)
        assert result is True
        assert state.get_energy("farmer-01") == 40.0

    def test_deduct_energy_insufficient(self):
        state = _make_state_with_agent(energy=5.0)
        result = state.deduct_energy("farmer-01", 10.0)
        assert result is False
        assert state.get_energy("farmer-01") == 5.0  # Unchanged

    def test_add_energy_caps_at_max(self):
        state = _make_state_with_agent(energy=95.0)
        new_val = state.add_energy("farmer-01", 20.0)
        assert new_val == MAX_ENERGY
        assert state.get_energy("farmer-01") == MAX_ENERGY

    def test_add_energy_normal(self):
        state = _make_state_with_agent(energy=50.0)
        new_val = state.add_energy("farmer-01", 10.0)
        assert new_val == 60.0

    def test_get_all_energy(self):
        state = WorldState()
        state.register_energy("a")
        state.register_energy("b")
        state.set_energy("a", 80.0)
        state.set_energy("b", 60.0)
        levels = state.get_all_energy()
        assert levels == {"a": 80.0, "b": 60.0}

    def test_sheltered_status(self):
        state = WorldState()
        state.register_energy("a")
        assert state.is_sheltered("a") is False
        state.set_sheltered("a", True)
        assert state.is_sheltered("a") is True
        state.set_sheltered("a", False)
        assert state.is_sheltered("a") is False


class TestCheckGatherEnergy:
    def test_sufficient_energy(self):
        state = _make_state_with_agent(energy=50.0)
        error = check_gather_energy("farmer-01", state)
        assert error is None

    def test_exact_energy(self):
        cost = ACTION_ENERGY_COSTS["gather"]
        state = _make_state_with_agent(energy=cost)
        error = check_gather_energy("farmer-01", state)
        assert error is None

    def test_insufficient_energy(self):
        state = _make_state_with_agent(energy=5.0)
        error = check_gather_energy("farmer-01", state)
        assert error is not None
        assert "Insufficient energy" in error

    def test_zero_energy(self):
        state = _make_state_with_agent(energy=0.0)
        error = check_gather_energy("farmer-01", state)
        assert error is not None


class TestDeductGatherEnergy:
    def test_deducts_correct_amount(self):
        cost = ACTION_ENERGY_COSTS["gather"]
        state = _make_state_with_agent(energy=50.0)
        deduct_gather_energy("farmer-01", state)
        assert state.get_energy("farmer-01") == 50.0 - cost


class TestApplyRegen:
    def test_basic_regen(self):
        state = _make_state_with_agent(energy=50.0)
        result = apply_regen(state)
        expected = 50.0 + REGEN_PER_TICK
        assert result["farmer-01"] == expected
        assert state.get_energy("farmer-01") == expected

    def test_regen_caps_at_max(self):
        state = _make_state_with_agent(energy=98.0)
        result = apply_regen(state)
        assert result["farmer-01"] == MAX_ENERGY

    def test_shelter_bonus(self):
        state = _make_state_with_agent(energy=50.0)
        state.set_sheltered("farmer-01", True)
        result = apply_regen(state)
        expected = 50.0 + REGEN_PER_TICK + SHELTER_BONUS_REGEN
        assert result["farmer-01"] == expected

    def test_multiple_agents(self):
        state = WorldState()
        state.register_energy("a")
        state.register_energy("b")
        state.set_energy("a", 40.0)
        state.set_energy("b", 60.0)
        state.set_sheltered("b", True)
        result = apply_regen(state)
        assert result["a"] == 40.0 + REGEN_PER_TICK
        assert result["b"] == 60.0 + REGEN_PER_TICK + SHELTER_BONUS_REGEN

    def test_regen_empty_state(self):
        state = WorldState()
        result = apply_regen(state)
        assert result == {}


class TestGetEnergyCost:
    def test_gather_cost(self):
        assert get_energy_cost("gather") == 10.0

    def test_craft_start_cost(self):
        assert get_energy_cost("craft_start") == 15.0

    def test_offer_cost(self):
        assert get_energy_cost("offer") == 5.0

    def test_unknown_action_free(self):
        assert get_energy_cost("heartbeat") == 0.0

    def test_consume_free(self):
        assert get_energy_cost("consume") == 0.0


class TestProcessConsumeResult:
    def test_restores_energy(self):
        state = _make_state_with_agent(energy=40.0)
        new_val = process_consume_result("farmer-01", 30.0, state)
        assert new_val == 70.0
        assert state.get_energy("farmer-01") == 70.0

    def test_restores_capped_at_max(self):
        state = _make_state_with_agent(energy=90.0)
        new_val = process_consume_result("farmer-01", 30.0, state)
        assert new_val == MAX_ENERGY

    def test_restores_zero_energy(self):
        state = _make_state_with_agent(energy=0.0)
        new_val = process_consume_result("farmer-01", 30.0, state)
        assert new_val == 30.0
