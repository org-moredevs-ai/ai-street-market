"""Unit tests for energy system protocol models and constants."""

import pytest
from pydantic import ValidationError
from streetmarket import (
    ACTION_ENERGY_COSTS,
    FREE_AT_ZERO_ENERGY,
    ITEMS,
    MAX_ENERGY,
    PAYLOAD_REGISTRY,
    REGEN_PER_TICK,
    SHELTER_BONUS_REGEN,
    STARTING_ENERGY,
    MessageType,
)
from streetmarket.models.messages import Consume, ConsumeResult, EnergyUpdate


class TestEnergyConstants:
    def test_starting_energy(self):
        assert STARTING_ENERGY == 100.0

    def test_max_energy(self):
        assert MAX_ENERGY == 100.0

    def test_regen_per_tick(self):
        assert REGEN_PER_TICK == 5.0

    def test_shelter_bonus_regen(self):
        assert SHELTER_BONUS_REGEN == 3.0

    def test_gather_costs_10(self):
        assert ACTION_ENERGY_COSTS[MessageType.GATHER] == 10.0

    def test_craft_start_costs_15(self):
        assert ACTION_ENERGY_COSTS[MessageType.CRAFT_START] == 15.0

    def test_offer_costs_5(self):
        assert ACTION_ENERGY_COSTS[MessageType.OFFER] == 5.0

    def test_bid_costs_5(self):
        assert ACTION_ENERGY_COSTS[MessageType.BID] == 5.0

    def test_accept_costs_5(self):
        assert ACTION_ENERGY_COSTS[MessageType.ACCEPT] == 5.0

    def test_consume_free_at_zero(self):
        assert MessageType.CONSUME in FREE_AT_ZERO_ENERGY

    def test_join_free_at_zero(self):
        assert MessageType.JOIN in FREE_AT_ZERO_ENERGY

    def test_heartbeat_free_at_zero(self):
        assert MessageType.HEARTBEAT in FREE_AT_ZERO_ENERGY

    def test_accept_free_at_zero(self):
        assert MessageType.ACCEPT in FREE_AT_ZERO_ENERGY


class TestConsumeModel:
    def test_valid_consume(self):
        c = Consume(item="soup", quantity=1)
        assert c.item == "soup"
        assert c.quantity == 1

    def test_default_quantity_is_one(self):
        c = Consume(item="soup")
        assert c.quantity == 1

    def test_invalid_zero_quantity(self):
        with pytest.raises(ValidationError):
            Consume(item="soup", quantity=0)


class TestConsumeResultModel:
    def test_valid_result(self):
        r = ConsumeResult(
            reference_msg_id="msg-1",
            agent_id="farmer-01",
            item="soup",
            quantity=1,
            success=True,
            energy_restored=30.0,
        )
        assert r.success is True
        assert r.energy_restored == 30.0

    def test_failed_result(self):
        r = ConsumeResult(
            reference_msg_id="msg-1",
            agent_id="farmer-01",
            item="soup",
            quantity=1,
            success=False,
            reason="No soup in inventory",
        )
        assert r.success is False
        assert r.reason == "No soup in inventory"


class TestEnergyUpdateModel:
    def test_valid_update(self):
        u = EnergyUpdate(tick=5, energy_levels={"farmer-01": 80.0, "chef-01": 60.0})
        assert u.tick == 5
        assert u.energy_levels["farmer-01"] == 80.0

    def test_empty_levels(self):
        u = EnergyUpdate(tick=1, energy_levels={})
        assert u.energy_levels == {}

    def test_invalid_tick_zero(self):
        with pytest.raises(ValidationError):
            EnergyUpdate(tick=0, energy_levels={})


class TestMessageTypeExtensions:
    def test_consume_type_exists(self):
        assert MessageType.CONSUME == "consume"

    def test_consume_result_type_exists(self):
        assert MessageType.CONSUME_RESULT == "consume_result"

    def test_energy_update_type_exists(self):
        assert MessageType.ENERGY_UPDATE == "energy_update"


class TestPayloadRegistry:
    def test_consume_registered(self):
        assert PAYLOAD_REGISTRY[MessageType.CONSUME] is Consume

    def test_consume_result_registered(self):
        assert PAYLOAD_REGISTRY[MessageType.CONSUME_RESULT] is ConsumeResult

    def test_energy_update_registered(self):
        assert PAYLOAD_REGISTRY[MessageType.ENERGY_UPDATE] is EnergyUpdate


class TestCatalogueEnergyRestore:
    def test_soup_restores_30(self):
        assert ITEMS["soup"].energy_restore == 30.0

    def test_potato_restores_zero(self):
        assert ITEMS["potato"].energy_restore == 0.0

    def test_wood_restores_zero(self):
        assert ITEMS["wood"].energy_restore == 0.0


class TestValidationResultAgentId:
    def test_agent_id_field_exists(self):
        from streetmarket.models.messages import ValidationResult
        r = ValidationResult(
            reference_msg_id="msg-1",
            valid=True,
            agent_id="farmer-01",
        )
        assert r.agent_id == "farmer-01"

    def test_agent_id_defaults_to_none(self):
        from streetmarket.models.messages import ValidationResult
        r = ValidationResult(reference_msg_id="msg-1", valid=True)
        assert r.agent_id is None


class TestAgentStateEnergy:
    def test_default_energy(self):
        from streetmarket.agent.state import AgentState
        state = AgentState(agent_id="test")
        assert state.energy == 100.0

    def test_custom_energy(self):
        from streetmarket.agent.state import AgentState
        state = AgentState(agent_id="test", energy=50.0)
        assert state.energy == 50.0


class TestActionKindConsume:
    def test_consume_action_exists(self):
        from streetmarket.agent.actions import ActionKind
        assert ActionKind.CONSUME == "consume"

    def test_all_kinds_include_consume(self):
        from streetmarket.agent.actions import ActionKind
        assert "consume" in {k.value for k in ActionKind}
