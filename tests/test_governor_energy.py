"""Unit tests for Governor energy validation."""

from streetmarket import Envelope, MessageType
from streetmarket.models.energy import ACTION_ENERGY_COSTS, STARTING_ENERGY

from services.governor.rules import validate_business_rules
from services.governor.state import GovernorState


def _make_envelope(
    msg_type: str,
    payload: dict,
    from_agent: str = "farmer-01",
    topic: str = "/market/raw-goods",
) -> Envelope:
    return Envelope(
        **{"from": from_agent},
        topic=topic,
        tick=5,
        type=msg_type,
        payload=payload,
    )


def _make_state_with_energy(
    agent_id: str = "farmer-01", energy: float = STARTING_ENERGY
) -> GovernorState:
    """Create a GovernorState with energy snapshot."""
    state = GovernorState(current_tick=5)
    state.register_agent(agent_id)
    state.update_energy({agent_id: energy})
    return state


class TestGovernorEnergyCheck:
    def test_offer_allowed_with_energy(self):
        state = _make_state_with_energy(energy=50.0)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_offer_rejected_low_energy(self):
        state = _make_state_with_energy(energy=3.0)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "Insufficient energy" in errors[0]

    def test_bid_rejected_low_energy(self):
        state = _make_state_with_energy(energy=3.0)
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 5, "max_price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert "Insufficient energy" in errors[0]

    def test_craft_start_rejected_low_energy(self):
        state = _make_state_with_energy(energy=10.0)  # craft_start needs 15
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            topic="/market/food",
        )
        errors = validate_business_rules(env, state)
        assert "Insufficient energy" in errors[0]

    def test_craft_start_allowed_with_energy(self):
        state = _make_state_with_energy(energy=20.0)
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            topic="/market/food",
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_exact_energy_allowed(self):
        cost = ACTION_ENERGY_COSTS[MessageType.OFFER]
        state = _make_state_with_energy(energy=cost)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_zero_energy_blocks_gather_type_actions(self):
        """Actions that cost energy should be blocked at 0."""
        state = _make_state_with_energy(energy=0.0)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 1, "price_per_unit": 1.0},
        )
        errors = validate_business_rules(env, state)
        assert "Insufficient energy" in errors[0]


class TestFreeAtZeroEnergy:
    def test_consume_allowed_at_zero_energy(self):
        state = _make_state_with_energy(energy=0.0)
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            topic="/market/food",
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_join_allowed_at_zero_energy(self):
        state = GovernorState(current_tick=5)
        state.update_energy({"new-agent": 0.0})
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "new-agent", "name": "New", "description": "New agent"},
            from_agent="new-agent",
            topic="/market/square",
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_heartbeat_allowed_at_zero_energy(self):
        state = _make_state_with_energy(energy=0.0)
        env = _make_envelope(
            MessageType.HEARTBEAT,
            {"agent_id": "farmer-01", "wallet": 100.0, "inventory_count": 5},
            topic="/market/square",
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_accept_allowed_at_zero_energy(self):
        """ACCEPT is free at zero — allows buying food to consume."""
        state = _make_state_with_energy(energy=0.0)
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "msg-1", "quantity": 1},
        )
        errors = validate_business_rules(env, state)
        assert errors == []


class TestConsumeValidation:
    def test_valid_consume_soup(self):
        state = _make_state_with_energy(energy=50.0)
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            topic="/market/food",
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_consume_non_consumable_item(self):
        state = _make_state_with_energy(energy=50.0)
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "potato", "quantity": 1},
            topic="/market/raw-goods",
        )
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "not consumable" in errors[0]

    def test_consume_unknown_item(self):
        state = _make_state_with_energy(energy=50.0)
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "diamond", "quantity": 1},
            topic="/market/general",
        )
        errors = validate_business_rules(env, state)
        assert "Unknown item" in errors[0]


class TestGovernorStateEnergy:
    def test_update_energy(self):
        state = GovernorState()
        state.update_energy({"a": 80.0, "b": 60.0})
        assert state.get_energy("a") == 80.0
        assert state.get_energy("b") == 60.0

    def test_get_energy_unknown(self):
        state = GovernorState()
        assert state.get_energy("unknown") == 0.0

    def test_update_energy_replaces(self):
        state = GovernorState()
        state.update_energy({"a": 80.0})
        state.update_energy({"a": 50.0, "b": 70.0})
        assert state.get_energy("a") == 50.0
        assert state.get_energy("b") == 70.0


class TestValidationResultAgentId:
    def test_business_rules_pass_for_known_agent(self):
        """Verify the Governor still validates known agents correctly."""
        state = _make_state_with_energy(energy=50.0)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert errors == []
