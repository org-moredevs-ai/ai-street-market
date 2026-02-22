"""Unit tests for the Agent SDK — state, actions, helpers."""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer, PendingOffer


class TestActionKind:
    def test_all_kinds_exist(self):
        expected = {
            "gather", "offer", "bid", "accept",
            "craft_start", "craft_complete", "heartbeat", "join",
        }
        assert {k.value for k in ActionKind} == expected

    def test_action_is_frozen(self):
        action = Action(kind=ActionKind.GATHER, params={"item": "potato"})
        assert action.kind == ActionKind.GATHER
        assert action.params["item"] == "potato"


class TestCraftingJob:
    def test_complete_at_tick(self):
        job = CraftingJob(recipe="soup", started_tick=5, duration_ticks=2)
        assert job.complete_at_tick == 7

    def test_is_done_before(self):
        job = CraftingJob(recipe="soup", started_tick=5, duration_ticks=2)
        assert not job.is_done(6)

    def test_is_done_exact(self):
        job = CraftingJob(recipe="soup", started_tick=5, duration_ticks=2)
        assert job.is_done(7)

    def test_is_done_after(self):
        job = CraftingJob(recipe="soup", started_tick=5, duration_ticks=2)
        assert job.is_done(10)


class TestAgentState:
    def _make_state(self, **kwargs) -> AgentState:
        return AgentState(agent_id="test-agent", **kwargs)

    def test_initial_state(self):
        state = self._make_state()
        assert state.agent_id == "test-agent"
        assert state.joined is False
        assert state.wallet == 0.0
        assert state.inventory == {}
        assert state.current_tick == 0

    def test_inventory_count_empty(self):
        state = self._make_state()
        assert state.inventory_count("potato") == 0

    def test_inventory_count_with_items(self):
        state = self._make_state(inventory={"potato": 10, "onion": 5})
        assert state.inventory_count("potato") == 10
        assert state.inventory_count("onion") == 5
        assert state.inventory_count("wood") == 0

    def test_has_items_true(self):
        state = self._make_state(inventory={"potato": 10, "onion": 5})
        assert state.has_items({"potato": 2, "onion": 1})

    def test_has_items_false_insufficient(self):
        state = self._make_state(inventory={"potato": 1, "onion": 5})
        assert not state.has_items({"potato": 2, "onion": 1})

    def test_has_items_false_missing(self):
        state = self._make_state(inventory={"potato": 10})
        assert not state.has_items({"potato": 2, "onion": 1})

    def test_has_items_empty_requirements(self):
        state = self._make_state()
        assert state.has_items({})

    def test_is_crafting(self):
        state = self._make_state()
        assert not state.is_crafting()
        state.active_craft = CraftingJob(recipe="soup", started_tick=1, duration_ticks=2)
        assert state.is_crafting()

    def test_needs_heartbeat(self):
        state = self._make_state()
        state.current_tick = 1
        assert not state.needs_heartbeat(5)
        state.current_tick = 5
        assert state.needs_heartbeat(5)
        state.last_heartbeat_tick = 5
        state.current_tick = 9
        assert not state.needs_heartbeat(5)
        state.current_tick = 10
        assert state.needs_heartbeat(5)

    def test_remaining_actions(self):
        state = self._make_state()
        assert state.remaining_actions(5) == 5
        state.actions_this_tick = 3
        assert state.remaining_actions(5) == 2
        state.actions_this_tick = 5
        assert state.remaining_actions(5) == 0
        state.actions_this_tick = 7
        assert state.remaining_actions(5) == 0

    def test_add_inventory(self):
        state = self._make_state()
        state.add_inventory("potato", 5)
        assert state.inventory_count("potato") == 5
        state.add_inventory("potato", 3)
        assert state.inventory_count("potato") == 8

    def test_remove_inventory_success(self):
        state = self._make_state(inventory={"potato": 10})
        assert state.remove_inventory("potato", 3)
        assert state.inventory_count("potato") == 7

    def test_remove_inventory_exact(self):
        state = self._make_state(inventory={"potato": 5})
        assert state.remove_inventory("potato", 5)
        assert state.inventory_count("potato") == 0
        assert "potato" not in state.inventory

    def test_remove_inventory_insufficient(self):
        state = self._make_state(inventory={"potato": 2})
        assert not state.remove_inventory("potato", 5)
        assert state.inventory_count("potato") == 2

    def test_remove_inventory_missing(self):
        state = self._make_state()
        assert not state.remove_inventory("potato", 1)

    def test_advance_tick(self):
        state = self._make_state()
        state.actions_this_tick = 3
        state.observed_offers.append(
            ObservedOffer(
                msg_id="m1",
                from_agent="other",
                item="potato",
                quantity=5,
                price_per_unit=2.0,
                is_sell=True,
            )
        )
        state.advance_tick(10)
        assert state.current_tick == 10
        assert state.actions_this_tick == 0
        assert state.observed_offers == []


class TestPendingOffer:
    def test_create_sell(self):
        po = PendingOffer(
            msg_id="m1", item="potato", quantity=10, price_per_unit=2.4, tick=5, is_sell=True
        )
        assert po.is_sell is True
        assert po.item == "potato"

    def test_create_buy(self):
        po = PendingOffer(
            msg_id="m2", item="onion", quantity=5, price_per_unit=3.0, tick=5, is_sell=False
        )
        assert po.is_sell is False


class TestObservedOffer:
    def test_create(self):
        oo = ObservedOffer(
            msg_id="m1",
            from_agent="farmer-01",
            item="potato",
            quantity=10,
            price_per_unit=2.4,
            is_sell=True,
        )
        assert oo.from_agent == "farmer-01"
        assert oo.is_sell is True
