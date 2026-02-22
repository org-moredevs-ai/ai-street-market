"""Unit tests for Mason strategy — pure function, no NATS."""

from streetmarket.agent.actions import ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer

from agents.mason.strategy import decide


def _make_state(**kwargs) -> AgentState:
    defaults = {
        "agent_id": "mason-01",
        "joined": True,
        "wallet": 100.0,
        "current_tick": 5,
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


class TestMasonGather:
    def test_gathers_stone_from_spawn(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"stone": 10, "wood": 15, "potato": 20},
        )
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 1
        assert gathers[0].params["item"] == "stone"

    def test_gather_stone_quantity(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"stone": 15},
        )
        actions = decide(state)
        stone_gather = next(a for a in actions if a.kind == ActionKind.GATHER)
        assert stone_gather.params["quantity"] == 8

    def test_gather_limited_by_spawn(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"stone": 3},
        )
        actions = decide(state)
        stone_gather = next(a for a in actions if a.kind == ActionKind.GATHER)
        assert stone_gather.params["quantity"] == 3

    def test_no_gather_without_spawn(self):
        state = _make_state(current_spawn_id=None)
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 0

    def test_no_gather_if_no_stone(self):
        state = _make_state(
            current_spawn_id="sp-1",
            current_spawn_items={"wood": 15},
        )
        actions = decide(state)
        gathers = [a for a in actions if a.kind == ActionKind.GATHER]
        assert len(gathers) == 0


class TestMasonBuyWood:
    def test_accepts_wood_offer(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="lumberjack-01",
                    item="wood",
                    quantity=3,
                    price_per_unit=3.0,  # base_price for wood
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "off-1"

    def test_rejects_expensive_wood(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="lumberjack-01",
                    item="wood",
                    quantity=3,
                    price_per_unit=6.0,  # 2x base (3.0), above 1.5x
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignores_non_wood_offers(self):
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
        assert len(accepts) == 0


class TestMasonCrafting:
    def test_craft_wall_when_has_ingredients(self):
        state = _make_state(inventory={"stone": 5, "wood": 3})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 1
        assert crafts[0].params["recipe"] == "wall"

    def test_no_craft_without_ingredients(self):
        state = _make_state(inventory={"stone": 3, "wood": 1})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0

    def test_no_craft_while_crafting(self):
        state = _make_state(
            inventory={"stone": 5, "wood": 3},
            active_craft=CraftingJob(recipe="wall", started_tick=3, duration_ticks=4),
        )
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0


class TestMasonSellWall:
    def test_offers_wall(self):
        state = _make_state(inventory={"wall": 2})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 1
        assert offers[0].params["item"] == "wall"
        assert offers[0].params["quantity"] == 2
        assert offers[0].params["price_per_unit"] == 18.0

    def test_no_offer_without_wall(self):
        state = _make_state(inventory={})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0


class TestMasonAcceptBids:
    def test_accepts_bid_at_base_price(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="buyer-01",
                    item="wall",
                    quantity=1,
                    price_per_unit=15.0,
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "bid-1"

    def test_rejects_bid_below_base(self):
        state = _make_state(
            observed_offers=[
                ObservedOffer(
                    msg_id="bid-1",
                    from_agent="buyer-01",
                    item="wall",
                    quantity=1,
                    price_per_unit=10.0,
                    is_sell=False,
                ),
            ],
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0


class TestMasonBidForWood:
    def test_bids_for_wood_when_needed(self):
        state = _make_state(inventory={"stone": 5})  # Has stone but no wood
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 1
        assert bids[0].params["item"] == "wood"
        assert bids[0].params["quantity"] == 2  # wall needs 2 wood

    def test_no_bid_when_has_wood(self):
        state = _make_state(inventory={"stone": 5, "wood": 3})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0

    def test_no_bid_when_wood_offers_exist(self):
        state = _make_state(
            inventory={"stone": 5},
            observed_offers=[
                ObservedOffer(
                    msg_id="off-1",
                    from_agent="lumberjack-01",
                    item="wood",
                    quantity=3,
                    price_per_unit=3.0,
                    is_sell=True,
                ),
            ],
        )
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0


class TestMasonEnergy:
    def test_consumes_soup_when_low(self):
        state = _make_state(energy=20.0, inventory={"soup": 1})
        actions = decide(state)
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 1
        assert consumes[0].params["item"] == "soup"

    def test_no_consume_when_energy_ok(self):
        state = _make_state(energy=80.0, inventory={"soup": 1})
        actions = decide(state)
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 0

    def test_rest_when_critical(self):
        state = _make_state(
            energy=5.0,
            inventory={"soup": 1, "stone": 10},
            current_spawn_id="sp-1",
            current_spawn_items={"stone": 15},
        )
        actions = decide(state)
        kinds = {a.kind for a in actions}
        assert ActionKind.GATHER not in kinds
        assert ActionKind.OFFER not in kinds
        consumes = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consumes) == 1

    def test_rest_without_soup(self):
        state = _make_state(energy=5.0, inventory={})
        actions = decide(state)
        assert len(actions) == 0


class TestMasonActionBudget:
    def test_respects_action_limit(self):
        state = _make_state(
            actions_this_tick=4,
            current_spawn_id="sp-1",
            current_spawn_items={"stone": 10},
            inventory={"stone": 5, "wood": 3, "wall": 1},
        )
        actions = decide(state)
        assert len(actions) <= 1

    def test_empty_when_no_budget(self):
        state = _make_state(actions_this_tick=5)
        actions = decide(state)
        assert len(actions) == 0
