"""Unit tests for Farmer strategy — pure function, no NATS."""

from streetmarket.agent.actions import ActionKind
from streetmarket.agent.state import AgentState, ObservedOffer

from agents.farmer.strategy import decide


def _make_state(**kwargs) -> AgentState:
    defaults = {
        "agent_id": "farmer-01",
        "joined": True,
        "wallet": 100.0,
        "current_tick": 5,
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


class TestFarmerGather:
    def test_gathers_from_spawn(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"potato": 20, "onion": 15, "wood": 10},
        )
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 2
        items = {a.params["item"] for a in gathers}
        assert items == {"potato", "onion"}

    def test_gather_potato_quantity(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"potato": 20, "onion": 15},
        )
        actions = decide(state)
        potato_gather = next(
            a for a in actions if a.kind == ActionKind.GATHER and a.params["item"] == "potato"
        )
        assert potato_gather.params["quantity"] == 10

    def test_gather_onion_quantity(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"potato": 20, "onion": 15},
        )
        actions = decide(state)
        onion_gather = next(
            a for a in actions if a.kind == ActionKind.GATHER and a.params["item"] == "onion"
        )
        assert onion_gather.params["quantity"] == 8

    def test_gather_limited_by_spawn(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"potato": 3, "onion": 2},
        )
        actions = decide(state)
        potato = next(
            a for a in actions if a.kind == ActionKind.GATHER and a.params["item"] == "potato"
        )
        onion = next(
            a for a in actions if a.kind == ActionKind.GATHER and a.params["item"] == "onion"
        )
        assert potato.params["quantity"] == 3
        assert onion.params["quantity"] == 2

    def test_no_gather_without_spawn(self):
        state = _make_state(current_spawn_id=None)
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 0

    def test_skip_item_not_in_spawn(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"wood": 10},
        )
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 0


class TestFarmerAcceptBids:
    def test_accepts_bid_at_base_price(self):
        state = _make_state(
            inventory={"potato": 10},
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="chef-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,  # base_price for potato
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "bid-1"

    def test_accepts_bid_above_base_price(self):
        state = _make_state(
            inventory={"potato": 10},
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="chef-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=3.0,
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1

    def test_rejects_bid_below_base_price(self):
        state = _make_state(
            inventory={"potato": 10},
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="chef-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=1.0,  # below base 2.0
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignores_sell_offers(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="other",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignores_bids_for_non_farmer_items(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="other",
                    item="wood",
                    quantity=5,
                    price_per_unit=5.0,
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0


class TestFarmerOffers:
    def test_offers_surplus(self):
        state = _make_state(inventory={"potato": 10, "onion": 5})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 2
        items = {a.params["item"] for a in offers}
        assert items == {"potato", "onion"}

    def test_offer_price_is_1_2x_base(self):
        state = _make_state(inventory={"potato": 10})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        potato_offer = next(o for o in offers if o.params["item"] == "potato")
        assert potato_offer.params["price_per_unit"] == 2.4  # 2.0 * 1.2

    def test_offer_quantity_is_surplus(self):
        state = _make_state(inventory={"potato": 7})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER and a.params["item"] == "potato"]
        assert len(offers) == 1
        assert offers[0].params["quantity"] == 5  # 7 - 2 reserve

    def test_no_offer_if_at_reserve(self):
        state = _make_state(inventory={"potato": 2})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER and a.params["item"] == "potato"]
        assert len(offers) == 0

    def test_no_offer_if_below_reserve(self):
        state = _make_state(inventory={"potato": 1})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER and a.params["item"] == "potato"]
        assert len(offers) == 0


class TestFarmerActionBudget:
    def test_respects_action_limit(self):
        state = _make_state(
            actions_this_tick=4,
            current_spawn_id="sp-1",
            current_spawn_items={"potato": 20, "onion": 15},
            inventory={"potato": 10, "onion": 10},
        )
        actions = decide(state)
        assert len(actions) <= 1  # Only 1 action remaining

    def test_empty_when_no_budget(self):
        state = _make_state(actions_this_tick=5)
        actions = decide(state)
        assert len(actions) == 0
