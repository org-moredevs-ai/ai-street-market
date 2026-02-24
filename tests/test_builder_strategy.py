"""Tests for Builder strategy — Phase 8."""

from streetmarket.agent.actions import ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer

from agents.builder.strategy import (
    HOUSE_SELL_PRICE,
    decide,
)


def _state(**kwargs) -> AgentState:
    defaults = {"agent_id": "builder-01", "energy": 100.0, "wallet": 200.0}
    defaults.update(kwargs)
    return AgentState(**defaults)


# ── Energy management ───────────────────────────────────────────────────────


class TestBuilderEnergy:
    def test_consume_bread_when_energy_low(self) -> None:
        state = _state(energy=20.0, inventory={"bread": 1})
        actions = decide(state)
        consume = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consume) == 1
        assert consume[0].params["item"] == "bread"

    def test_consume_soup_fallback(self) -> None:
        state = _state(energy=20.0, inventory={"soup": 1})
        actions = decide(state)
        consume = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consume) == 1
        assert consume[0].params["item"] == "soup"

    def test_rest_mode_only_consume(self) -> None:
        state = _state(energy=5.0, inventory={"bread": 1, "wall": 4})
        actions = decide(state)
        assert len(actions) == 1
        assert actions[0].kind == ActionKind.CONSUME

    def test_no_actions_rest_no_food(self) -> None:
        state = _state(energy=5.0)
        actions = decide(state)
        assert len(actions) == 0


# ── Accept material offers ──────────────────────────────────────────────────


class TestBuilderAcceptOffers:
    def test_accept_wall_offer(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="mason", item="wall",
                    quantity=2, price_per_unit=18.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "offer-1"

    def test_accept_shelf_offer(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="lj", item="shelf",
                    quantity=1, price_per_unit=12.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1

    def test_reject_expensive_offer(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="mason", item="wall",
                    quantity=2, price_per_unit=50.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignore_non_ingredient_offers(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="farmer", item="potato",
                    quantity=10, price_per_unit=1.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0


# ── Craft house ─────────────────────────────────────────────────────────────


class TestBuilderCraft:
    def test_craft_house_with_ingredients(self) -> None:
        state = _state(inventory={"wall": 4, "shelf": 2, "furniture": 3})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 1
        assert crafts[0].params["recipe"] == "house"

    def test_no_craft_without_all_ingredients(self) -> None:
        state = _state(inventory={"wall": 4, "shelf": 2})  # Missing furniture
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0

    def test_no_craft_when_already_crafting(self) -> None:
        state = _state(
            inventory={"wall": 4, "shelf": 2, "furniture": 3},
            active_craft=CraftingJob(recipe="house", started_tick=1, duration_ticks=10),
        )
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0


# ── Offer house ─────────────────────────────────────────────────────────────


class TestBuilderOffer:
    def test_offer_house_when_available(self) -> None:
        state = _state(inventory={"house": 1})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 1
        assert offers[0].params["item"] == "house"
        assert offers[0].params["price_per_unit"] == HOUSE_SELL_PRICE

    def test_no_offer_without_house(self) -> None:
        state = _state(inventory={})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0


# ── Bid for materials ───────────────────────────────────────────────────────


class TestBuilderBid:
    def test_bid_for_missing_materials(self) -> None:
        state = _state(inventory={"wall": 2})  # Need wall=4, shelf=2, furniture=3
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) >= 1
        bid_items = {b.params["item"] for b in bids}
        assert "wall" in bid_items or "shelf" in bid_items or "furniture" in bid_items

    def test_no_bid_when_offers_visible(self) -> None:
        state = _state(
            inventory={"wall": 1},
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="mason", item="wall",
                    quantity=3, price_per_unit=18.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0

    def test_bid_quantity_is_deficit(self) -> None:
        state = _state(inventory={"wall": 3, "shelf": 2, "furniture": 3})
        # Only missing 1 wall
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        wall_bids = [b for b in bids if b.params["item"] == "wall"]
        assert len(wall_bids) == 1
        assert wall_bids[0].params["quantity"] == 1

    def test_no_bid_when_have_all_ingredients(self) -> None:
        state = _state(inventory={"wall": 4, "shelf": 2, "furniture": 3})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0
