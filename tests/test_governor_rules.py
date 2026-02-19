"""Tests for Governor Phase 1 business rules."""

from streetmarket import Envelope, MessageType

from services.governor.rules import validate_business_rules, validate_envelope_structure
from services.governor.state import MAX_ACTIONS_PER_TICK, GovernorState


def _make_envelope(
    msg_type: MessageType,
    payload: dict,
    from_agent: str = "farmer-01",
    topic: str = "/market/raw-goods",
    tick: int = 1,
) -> Envelope:
    """Helper to build envelopes for testing."""
    return Envelope(
        **{"from": from_agent},
        topic=topic,
        tick=tick,
        type=msg_type,
        payload=payload,
    )


class TestEnvelopeStructure:
    def test_valid_offer_passes(self):
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        assert validate_envelope_structure(env) == []

    def test_missing_payload_field_fails(self):
        env = _make_envelope(MessageType.OFFER, {"item": "potato"})
        errors = validate_envelope_structure(env)
        assert len(errors) > 0
        assert any("quantity" in e for e in errors)


class TestRateLimit:
    def test_under_limit_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        for _ in range(MAX_ACTIONS_PER_TICK - 1):
            state.record_action("farmer-01")
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_at_limit_rejected(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        for _ in range(MAX_ACTIONS_PER_TICK):
            state.record_action("farmer-01")
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "Rate limited" in errors[0]

    def test_rate_limit_is_per_agent(self):
        state = GovernorState()
        for _ in range(MAX_ACTIONS_PER_TICK):
            state.record_action("farmer-01")
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
            from_agent="farmer-02",
        )
        errors = validate_business_rules(env, state)
        assert errors == []


class TestInactiveAgent:
    def test_inactive_agent_warned(self):
        state = GovernorState()
        state.advance_tick(0)
        state.record_heartbeat("farmer-01")
        state.advance_tick(20)  # Well past timeout
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert any("inactive" in e for e in errors)

    def test_active_agent_no_warning(self):
        state = GovernorState()
        state.advance_tick(5)
        state.record_heartbeat("farmer-01")
        state.advance_tick(10)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
        )
        errors = validate_business_rules(env, state)
        assert not any("inactive" in e for e in errors)


class TestOfferValidation:
    def test_valid_item_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        assert validate_business_rules(env, state) == []

    def test_unknown_item_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "diamond", "quantity": 1, "price_per_unit": 100.0},
        )
        errors = validate_business_rules(env, state)
        assert any("Unknown item" in e for e in errors)

    def test_crafted_item_allowed_in_offer(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "soup", "quantity": 1, "price_per_unit": 8.0},
        )
        assert validate_business_rules(env, state) == []


class TestBidValidation:
    def test_valid_item_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.BID,
            {"item": "wood", "quantity": 5, "max_price_per_unit": 4.0},
        )
        assert validate_business_rules(env, state) == []

    def test_unknown_item_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.BID,
            {"item": "gold", "quantity": 1, "max_price_per_unit": 50.0},
        )
        errors = validate_business_rules(env, state)
        assert any("Unknown item" in e for e in errors)


class TestAcceptValidation:
    def test_with_reference_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "msg-123", "quantity": 5},
        )
        assert validate_business_rules(env, state) == []

    def test_empty_reference_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "", "quantity": 5},
        )
        errors = validate_business_rules(env, state)
        assert any("reference_msg_id" in e for e in errors)


class TestCounterValidation:
    def test_with_reference_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.COUNTER,
            {"reference_msg_id": "msg-123", "proposed_price": 5.0, "quantity": 3},
        )
        assert validate_business_rules(env, state) == []

    def test_empty_reference_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.COUNTER,
            {"reference_msg_id": "", "proposed_price": 5.0, "quantity": 3},
        )
        errors = validate_business_rules(env, state)
        assert any("reference_msg_id" in e for e in errors)


class TestCraftStartValidation:
    def test_valid_recipe_passes(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
        )
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_unknown_recipe_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "cake", "inputs": {"sugar": 1}, "estimated_ticks": 1},
        )
        errors = validate_business_rules(env, state)
        assert any("Unknown recipe" in e for e in errors)

    def test_wrong_inputs_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 1, "onion": 1}, "estimated_ticks": 2},
        )
        errors = validate_business_rules(env, state)
        assert any("Inputs mismatch" in e for e in errors)

    def test_wrong_estimated_ticks_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 5},
        )
        errors = validate_business_rules(env, state)
        assert any("ticks mismatch" in e for e in errors)

    def test_already_crafting_fails(self):
        state = GovernorState()
        state.start_craft("farmer-01", "shelf", 3)
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
        )
        errors = validate_business_rules(env, state)
        assert any("already crafting" in e for e in errors)

    def test_valid_craft_updates_state(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
        )
        validate_business_rules(env, state)
        assert state.is_crafting("farmer-01")


class TestCraftCompleteValidation:
    def test_with_active_craft_passes(self):
        state = GovernorState()
        state.start_craft("farmer-01", "soup", 2)
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "farmer-01"},
        )
        errors = validate_business_rules(env, state)
        assert errors == []
        assert not state.is_crafting("farmer-01")

    def test_without_active_craft_fails(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "farmer-01"},
        )
        errors = validate_business_rules(env, state)
        assert any("no active craft" in e for e in errors)


class TestJoinValidation:
    def test_join_registers_agent(self):
        state = GovernorState()
        env = _make_envelope(
            MessageType.JOIN,
            {
                "agent_id": "farmer-01",
                "name": "Farmer",
                "description": "A potato farmer",
            },
            topic="/market/square",
        )
        errors = validate_business_rules(env, state)
        assert errors == []
        assert state.is_known_agent("farmer-01")


class TestHeartbeatValidation:
    def test_heartbeat_records_state(self):
        state = GovernorState()
        state.advance_tick(5)
        env = _make_envelope(
            MessageType.HEARTBEAT,
            {"agent_id": "farmer-01", "wallet": 100.0, "inventory_count": 10},
        )
        errors = validate_business_rules(env, state)
        assert errors == []
        assert not state.is_inactive("farmer-01")
