"""Tests for Baker strategy — Phase 7."""

from streetmarket.agent.actions import ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer

from agents.baker.strategy import (
    BREAD_SELL_PRICE,
    decide,
)


def _state(**kwargs) -> AgentState:
    defaults = {"agent_id": "baker-01", "energy": 100.0, "wallet": 100.0}
    defaults.update(kwargs)
    return AgentState(**defaults)


# ── Energy management ───────────────────────────────────────────────────────


class TestBakerEnergy:
    def test_consume_bread_when_energy_low(self) -> None:
        state = _state(energy=20.0, inventory={"bread": 2})
        actions = decide(state)
        consume = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consume) == 1
        assert consume[0].params["item"] == "bread"

    def test_consume_soup_fallback_when_no_bread(self) -> None:
        state = _state(energy=20.0, inventory={"soup": 1})
        actions = decide(state)
        consume = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consume) == 1
        assert consume[0].params["item"] == "soup"

    def test_no_consume_when_energy_high(self) -> None:
        state = _state(energy=80.0, inventory={"bread": 5})
        actions = decide(state)
        consume = [a for a in actions if a.kind == ActionKind.CONSUME]
        assert len(consume) == 0

    def test_rest_only_consume_when_critical(self) -> None:
        state = _state(energy=5.0, inventory={"bread": 1, "potato": 10})
        actions = decide(state)
        # Should only consume, no other actions
        assert len(actions) == 1
        assert actions[0].kind == ActionKind.CONSUME

    def test_no_actions_when_critical_and_no_food(self) -> None:
        state = _state(energy=5.0, inventory={"potato": 10})
        actions = decide(state)
        assert len(actions) == 0


# ── Accept potato offers ────────────────────────────────────────────────────


class TestBakerAcceptOffers:
    def test_accept_cheap_potato_offer(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="farmer", item="potato",
                    quantity=5, price_per_unit=2.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 1
        assert accepts[0].params["reference_msg_id"] == "offer-1"

    def test_reject_expensive_potato_offer(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="farmer", item="potato",
                    quantity=5, price_per_unit=10.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0

    def test_ignore_non_potato_offers(self) -> None:
        state = _state(
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="farmer", item="onion",
                    quantity=5, price_per_unit=1.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        accepts = [a for a in actions if a.kind == ActionKind.ACCEPT]
        assert len(accepts) == 0


# ── Craft bread ─────────────────────────────────────────────────────────────


class TestBakerCraft:
    def test_craft_bread_with_ingredients(self) -> None:
        state = _state(inventory={"potato": 5})
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 1
        assert crafts[0].params["recipe"] == "bread"

    def test_no_craft_without_ingredients(self) -> None:
        state = _state(inventory={"potato": 2})  # Need 3
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0

    def test_no_craft_when_already_crafting(self) -> None:
        state = _state(
            inventory={"potato": 5},
            active_craft=CraftingJob(recipe="bread", started_tick=1, duration_ticks=2),
        )
        actions = decide(state)
        crafts = [a for a in actions if a.kind == ActionKind.CRAFT_START]
        assert len(crafts) == 0


# ── Offer bread ─────────────────────────────────────────────────────────────


class TestBakerOffer:
    def test_offer_bread_when_surplus(self) -> None:
        state = _state(inventory={"bread": 3})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 1
        assert offers[0].params["item"] == "bread"
        assert offers[0].params["quantity"] == 2  # Keep 1
        assert offers[0].params["price_per_unit"] == BREAD_SELL_PRICE

    def test_no_offer_with_only_one_bread(self) -> None:
        state = _state(inventory={"bread": 1})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0

    def test_no_offer_with_zero_bread(self) -> None:
        state = _state(inventory={})
        actions = decide(state)
        offers = [a for a in actions if a.kind == ActionKind.OFFER]
        assert len(offers) == 0


# ── Bid for potato ──────────────────────────────────────────────────────────


class TestBakerBid:
    def test_bid_for_potato_when_no_offers(self) -> None:
        state = _state(inventory={"potato": 1})  # Need 3, have 1
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 1
        assert bids[0].params["item"] == "potato"
        assert bids[0].params["quantity"] == 2  # 3 - 1

    def test_no_bid_when_offers_visible(self) -> None:
        state = _state(
            inventory={"potato": 1},
            observed_offers=[
                ObservedOffer(
                    msg_id="offer-1", from_agent="farmer", item="potato",
                    quantity=5, price_per_unit=2.0, is_sell=True,
                ),
            ]
        )
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0

    def test_no_bid_when_have_enough_potato(self) -> None:
        state = _state(inventory={"potato": 5})
        actions = decide(state)
        bids = [a for a in actions if a.kind == ActionKind.BID]
        assert len(bids) == 0
