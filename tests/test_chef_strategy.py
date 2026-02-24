"""Unit tests for Chef strategy — pure function, no NATS."""

from streetmarket.agent.actions import ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer

from agents.chef.strategy import decide_hardcoded as decide


def _make_state(**kwargs) -> AgentState:
    defaults = {
        "agent_id": "chef-01",
        "joined": True,
        "wallet": 100.0,
        "current_tick": 5,
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


class TestChefAcceptOffers:
    def test_accepts_cheapest_offer(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="farmer-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "off-1"

    def test_accepts_offer_at_max_price(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="farmer-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=3.0,  # 1.5x base (2.0)
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1

    def test_rejects_expensive_offer(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="farmer-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=4.0,  # 2x base, above 1.5x
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_prefers_cheapest(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-exp",
                    from_agent="f1",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.8,
                    is_sell=True,
                ),
                ObservedOffer(
                    msg_id="off-cheap",
                    from_agent="f2",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 2
        # Cheapest first
        assert accepts[0].params["reference_msg_id"] == "off-cheap"

    def test_ignores_bids(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="other",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignores_non_ingredient_offers(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="other",
                    item="wood",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0


class TestChefCrafting:
    def test_craft_when_has_ingredients(self):
        state = _make_state(inventory={"potato": 3, "onion": 2})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 1
        assert crafts[0].params["recipe"] == "soup"

    def test_no_craft_if_missing_ingredient(self):
        state = _make_state(inventory={"potato": 3})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0

    def test_no_craft_if_insufficient(self):
        state = _make_state(inventory={"potato": 1, "onion": 1})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0

    def test_no_craft_if_already_crafting(self):
        state = _make_state(
            inventory={"potato": 3, "onion": 2},
            active_craft=CraftingJob(recipe="soup", started_tick=3, duration_ticks=2),
        )
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0


class TestChefSellSoup:
    def test_offers_soup_keeps_one_reserve(self):
        """Chef keeps 1 soup in reserve for emergency consuming."""
        state = _make_state(inventory={"soup": 3})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 1
        assert offers[0].params["item"] == "soup"
        assert offers[0].params["quantity"] == 2  # 3 - 1 reserve
        assert offers[0].params["price_per_unit"] == 10.0

    def test_no_offer_with_single_soup(self):
        """Don't sell last soup — keep for emergency."""
        state = _make_state(inventory={"soup": 1})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0

    def test_no_offer_without_soup(self):
        state = _make_state(inventory={})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0


class TestChefBidForIngredients:
    def test_bids_when_no_offers_and_missing_ingredients(self):
        state = _make_state(inventory={})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 2
        items = {a.params["item"] for a in bids}
        assert items == {"potato", "onion"}

    def test_bid_quantity_is_deficit(self):
        state = _make_state(inventory={"potato": 1})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        potato_bid = next(b for b in bids if b.params["item"] == "potato")
        assert potato_bid.params["quantity"] == 1  # needs 2, has 1

    def test_no_bid_when_offers_exist(self):
        state = _make_state(
            inventory={},
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="farmer-01",
                    item="potato",
                    quantity=5,
                    price_per_unit=2.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0

    def test_no_bid_if_have_enough(self):
        state = _make_state(inventory={"potato": 5, "onion": 3})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0


class TestChefActionBudget:
    def test_respects_action_limit(self):
        state = _make_state(
            actions_this_tick=4,
            inventory={"potato": 5, "onion": 5, "soup": 3},
        )
        actions = decide(state)
        assert len(actions) <= 1

    def test_empty_when_no_budget(self):
        state = _make_state(actions_this_tick=5)
        actions = decide(state)
        assert len(actions) == 0


class TestChefEnergy:
    def test_consumes_soup_when_low_energy(self):
        state = _make_state(energy=20.0, inventory={"soup": 2})
        actions = decide(state)
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 1
        assert consumes[0].params["item"] == "soup"

    def test_no_consume_when_energy_ok(self):
        state = _make_state(energy=80.0, inventory={"soup": 2})
        actions = decide(state)
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 0

    def test_no_consume_without_soup(self):
        state = _make_state(energy=20.0, inventory={})
        actions = decide(state)
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 0

    def test_rest_when_critical_energy(self):
        state = _make_state(
            energy=5.0,
            inventory={"soup": 1, "potato": 5, "onion": 3},
        )
        actions = decide(state)
        kinds = {a.kind for a in actions}
        assert ActionKind.CRAFT_START not in kinds
        assert ActionKind.OFFER not in kinds
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 1

    def test_rest_without_soup_returns_empty(self):
        state = _make_state(energy=5.0, inventory={"potato": 5})
        actions = decide(state)
        assert len(actions) == 0

    def test_consume_counts_against_budget(self):
        state = _make_state(
            energy=20.0,
            inventory={"soup": 1, "potato": 5, "onion": 3},
            actions_this_tick=4,
        )
        actions = decide(state)
        assert len(actions) == 1
        assert actions[0].kind == ActionKind.CONSUME
