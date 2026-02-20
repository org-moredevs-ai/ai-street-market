"""Tests for Banker economic validation rules."""

from streetmarket import Envelope, MessageType

from services.banker.rules import (
    process_accept,
    process_bid,
    process_craft_complete,
    process_craft_start,
    process_gather_result,
    process_join,
    process_offer,
)
from services.banker.state import STARTING_WALLET, BankerState


def _make_envelope(
    msg_type: MessageType,
    payload: dict,
    from_agent: str = "farmer-01",
    topic: str = "/market/raw-goods",
    tick: int = 1,
    msg_id: str | None = None,
) -> Envelope:
    """Helper to build envelopes for testing."""
    env = Envelope(
        **{"from": from_agent},
        topic=topic,
        tick=tick,
        type=msg_type,
        payload=payload,
    )
    if msg_id is not None:
        env.id = msg_id
    return env


def _setup_agent_with_inventory(
    state: BankerState, agent_id: str, inventory: dict[str, int]
) -> None:
    """Create account and seed inventory for an agent."""
    state.create_account(agent_id)
    for item, qty in inventory.items():
        state.credit_inventory(agent_id, item, qty)


class TestProcessJoin:
    def test_creates_account(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "farmer-01", "name": "Farmer", "description": "A farmer"},
        )
        errors = process_join(env, state)
        assert errors == []
        assert state.has_account("farmer-01")
        assert state.get_account("farmer-01").wallet == STARTING_WALLET  # type: ignore[union-attr]

    def test_uses_agent_id_from_payload(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "payload-id", "name": "Agent", "description": "Test"},
            from_agent="envelope-id",
        )
        errors = process_join(env, state)
        assert errors == []
        assert state.has_account("payload-id")

    def test_no_op_on_rejoin(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        state.credit_inventory("farmer-01", "potato", 10)
        env = _make_envelope(
            MessageType.JOIN,
            {"agent_id": "farmer-01", "name": "Farmer", "description": "A farmer"},
        )
        errors = process_join(env, state)
        assert errors == []
        # Wallet and inventory unchanged
        assert state.get_account("farmer-01").wallet == 50.0  # type: ignore[union-attr]
        assert state.get_account("farmer-01").inventory["potato"] == 10  # type: ignore[union-attr]


class TestProcessOffer:
    def test_valid_offer_added_to_book(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 10})
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 3.0},
        )
        errors = process_offer(env, state)
        assert errors == []
        assert state.order_count() == 1
        order = state.get_order(env.id)
        assert order is not None
        assert order.item == "potato"
        assert order.quantity == 5
        assert order.price_per_unit == 3.0

    def test_no_account_rejected(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 3.0},
        )
        errors = process_offer(env, state)
        assert len(errors) == 1
        assert "No account" in errors[0]

    def test_insufficient_inventory_rejected(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 2})
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        errors = process_offer(env, state)
        assert len(errors) == 1
        assert "insufficient inventory" in errors[0]

    def test_offer_with_expires_tick(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 10})
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 3.0, "expires_tick": 10},
        )
        errors = process_offer(env, state)
        assert errors == []
        order = state.get_order(env.id)
        assert order is not None
        assert order.expires_tick == 10


class TestProcessBid:
    def test_valid_bid_added_to_book(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=100.0)
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 5, "max_price_per_unit": 4.0},
            from_agent="buyer-01",
        )
        errors = process_bid(env, state)
        assert errors == []
        assert state.order_count() == 1
        order = state.get_order(env.id)
        assert order is not None
        assert order.item == "potato"
        assert order.quantity == 5
        assert order.price_per_unit == 4.0

    def test_no_account_rejected(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 5, "max_price_per_unit": 4.0},
            from_agent="buyer-01",
        )
        errors = process_bid(env, state)
        assert len(errors) == 1
        assert "No account" in errors[0]

    def test_insufficient_funds_rejected(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=5.0)
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 10, "max_price_per_unit": 4.0},
            from_agent="buyer-01",
        )
        errors = process_bid(env, state)
        assert len(errors) == 1
        assert "insufficient funds" in errors[0]

    def test_exact_funds_accepted(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=20.0)
        env = _make_envelope(
            MessageType.BID,
            {"item": "potato", "quantity": 5, "max_price_per_unit": 4.0},
            from_agent="buyer-01",
        )
        errors = process_bid(env, state)
        assert errors == []


class TestProcessAcceptOffer:
    """ACCEPT referencing an OFFER: accepter is the buyer."""

    def _setup_trade(self, state: BankerState) -> str:
        """Set up seller with inventory + offer, buyer with funds. Returns offer msg_id."""
        _setup_agent_with_inventory(state, "seller-01", {"potato": 10})
        state.create_account("buyer-01", wallet=100.0)
        # Create an offer in the book
        from services.banker.state import OrderEntry
        offer_id = "offer-abc"
        state.add_order(
            OrderEntry(
                msg_id=offer_id,
                from_agent="seller-01",
                msg_type=MessageType.OFFER,
                item="potato",
                quantity=10,
                price_per_unit=3.0,
                tick=1,
            )
        )
        return offer_id

    def test_full_fill(self):
        state = BankerState()
        offer_id = self._setup_trade(state)
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": offer_id, "quantity": 10},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert result.errors == []
        assert result.buyer == "buyer-01"
        assert result.seller == "seller-01"
        assert result.item == "potato"
        assert result.quantity == 10
        assert result.total_price == 30.0
        # Buyer got potatoes, seller got money
        assert state.get_account("buyer-01").inventory["potato"] == 10  # type: ignore[union-attr]
        assert state.get_account("buyer-01").wallet == 70.0  # type: ignore[union-attr]
        assert state.get_account("seller-01").wallet == STARTING_WALLET + 30.0  # type: ignore[union-attr]
        # Seller's inventory reduced
        assert not state.has_inventory("seller-01", "potato", 1)
        # Order removed from book
        assert state.get_order(offer_id) is None

    def test_partial_fill(self):
        state = BankerState()
        offer_id = self._setup_trade(state)
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": offer_id, "quantity": 3},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert result.errors == []
        assert result.quantity == 3
        assert result.total_price == 9.0
        # Order still in book with reduced quantity
        remaining = state.get_order(offer_id)
        assert remaining is not None
        assert remaining.quantity == 7

    def test_accept_more_than_order_caps_at_order_qty(self):
        state = BankerState()
        offer_id = self._setup_trade(state)
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": offer_id, "quantity": 100},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert result.errors == []
        assert result.quantity == 10  # capped at order qty

    def test_missing_reference(self):
        state = BankerState()
        state.create_account("buyer-01")
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "nonexistent", "quantity": 5},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_insufficient_funds(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "seller-01", {"potato": 10})
        state.create_account("buyer-01", wallet=5.0)
        from services.banker.state import OrderEntry
        state.add_order(
            OrderEntry(
                msg_id="offer-1",
                from_agent="seller-01",
                msg_type=MessageType.OFFER,
                item="potato",
                quantity=10,
                price_per_unit=3.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "offer-1", "quantity": 10},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert len(result.errors) == 1
        assert "insufficient funds" in result.errors[0]

    def test_insufficient_inventory(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "seller-01", {"potato": 2})
        state.create_account("buyer-01", wallet=100.0)
        from services.banker.state import OrderEntry
        state.add_order(
            OrderEntry(
                msg_id="offer-1",
                from_agent="seller-01",
                msg_type=MessageType.OFFER,
                item="potato",
                quantity=10,
                price_per_unit=3.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "offer-1", "quantity": 5},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert len(result.errors) == 1
        assert "insufficient inventory" in result.errors[0]

    def test_self_trade_rejected(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 10})
        from services.banker.state import OrderEntry
        state.add_order(
            OrderEntry(
                msg_id="offer-1",
                from_agent="farmer-01",
                msg_type=MessageType.OFFER,
                item="potato",
                quantity=5,
                price_per_unit=3.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "offer-1", "quantity": 5},
            from_agent="farmer-01",
        )
        result = process_accept(env, state)
        assert len(result.errors) == 1
        assert "Self-trade" in result.errors[0]


class TestProcessAcceptBid:
    """ACCEPT referencing a BID: accepter is the seller."""

    def test_accept_bid_full_fill(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=100.0)
        _setup_agent_with_inventory(state, "seller-01", {"wood": 10})
        from services.banker.state import OrderEntry
        bid_id = "bid-abc"
        state.add_order(
            OrderEntry(
                msg_id=bid_id,
                from_agent="buyer-01",
                msg_type=MessageType.BID,
                item="wood",
                quantity=5,
                price_per_unit=4.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": bid_id, "quantity": 5},
            from_agent="seller-01",
        )
        result = process_accept(env, state)
        assert result.errors == []
        assert result.buyer == "buyer-01"
        assert result.seller == "seller-01"
        assert result.item == "wood"
        assert result.quantity == 5
        assert result.total_price == 20.0
        # Buyer got wood, paid money
        assert state.get_account("buyer-01").inventory["wood"] == 5  # type: ignore[union-attr]
        assert state.get_account("buyer-01").wallet == 80.0  # type: ignore[union-attr]
        # Seller got money, lost wood
        assert state.get_account("seller-01").wallet == STARTING_WALLET + 20.0  # type: ignore[union-attr]

    def test_accept_bid_partial_fill(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=100.0)
        _setup_agent_with_inventory(state, "seller-01", {"wood": 10})
        from services.banker.state import OrderEntry
        bid_id = "bid-abc"
        state.add_order(
            OrderEntry(
                msg_id=bid_id,
                from_agent="buyer-01",
                msg_type=MessageType.BID,
                item="wood",
                quantity=10,
                price_per_unit=4.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": bid_id, "quantity": 3},
            from_agent="seller-01",
        )
        result = process_accept(env, state)
        assert result.errors == []
        assert result.quantity == 3
        assert result.total_price == 12.0
        # Bid still in book with reduced quantity
        remaining = state.get_order(bid_id)
        assert remaining is not None
        assert remaining.quantity == 7

    def test_accept_bid_insufficient_buyer_funds(self):
        state = BankerState()
        state.create_account("buyer-01", wallet=5.0)
        _setup_agent_with_inventory(state, "seller-01", {"wood": 10})
        from services.banker.state import OrderEntry
        state.add_order(
            OrderEntry(
                msg_id="bid-1",
                from_agent="buyer-01",
                msg_type=MessageType.BID,
                item="wood",
                quantity=10,
                price_per_unit=4.0,
                tick=1,
            )
        )
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": "bid-1", "quantity": 10},
            from_agent="seller-01",
        )
        result = process_accept(env, state)
        assert len(result.errors) == 1
        assert "insufficient funds" in result.errors[0]


class TestProcessCraftStart:
    def test_valid_craft_debits_inputs(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "crafter-01", {"potato": 5, "onion": 3})
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            from_agent="crafter-01",
        )
        errors = process_craft_start(env, state)
        assert errors == []
        account = state.get_account("crafter-01")
        assert account is not None
        assert account.inventory["potato"] == 3
        assert account.inventory["onion"] == 2

    def test_no_account_rejected(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            from_agent="crafter-01",
        )
        errors = process_craft_start(env, state)
        assert len(errors) == 1
        assert "No account" in errors[0]

    def test_insufficient_inputs_rejected(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "crafter-01", {"potato": 1, "onion": 3})
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            from_agent="crafter-01",
        )
        errors = process_craft_start(env, state)
        assert len(errors) >= 1
        assert any("insufficient" in e for e in errors)
        # Inventory unchanged
        assert state.get_account("crafter-01").inventory["potato"] == 1  # type: ignore[union-attr]

    def test_missing_item_rejected(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "crafter-01", {"potato": 5})
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            from_agent="crafter-01",
        )
        errors = process_craft_start(env, state)
        assert len(errors) >= 1
        assert any("onion" in e for e in errors)

    def test_multiple_missing_items_reports_all(self):
        state = BankerState()
        state.create_account("crafter-01")  # empty inventory
        env = _make_envelope(
            MessageType.CRAFT_START,
            {"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            from_agent="crafter-01",
        )
        errors = process_craft_start(env, state)
        assert len(errors) == 2
        assert any("potato" in e for e in errors)
        assert any("onion" in e for e in errors)


class TestProcessCraftComplete:
    def test_credits_outputs(self):
        state = BankerState()
        state.create_account("crafter-01")
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "crafter-01"},
            from_agent="crafter-01",
        )
        errors = process_craft_complete(env, state)
        assert errors == []
        assert state.get_account("crafter-01").inventory["soup"] == 1  # type: ignore[union-attr]

    def test_no_account_rejected(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "crafter-01"},
            from_agent="crafter-01",
        )
        errors = process_craft_complete(env, state)
        assert len(errors) == 1
        assert "No account" in errors[0]

    def test_multiple_outputs_credited(self):
        state = BankerState()
        state.create_account("crafter-01")
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "test", "output": {"soup": 2, "wood": 3}, "agent": "crafter-01"},
            from_agent="crafter-01",
        )
        errors = process_craft_complete(env, state)
        assert errors == []
        account = state.get_account("crafter-01")
        assert account is not None
        assert account.inventory["soup"] == 2
        assert account.inventory["wood"] == 3

    def test_stacks_with_existing_inventory(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "crafter-01", {"soup": 3})
        env = _make_envelope(
            MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "crafter-01"},
            from_agent="crafter-01",
        )
        errors = process_craft_complete(env, state)
        assert errors == []
        assert state.get_account("crafter-01").inventory["soup"] == 4  # type: ignore[union-attr]


class TestProcessGatherResult:
    def test_credits_inventory(self):
        state = BankerState()
        state.create_account("farmer-01")
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {
                "reference_msg_id": "msg-1",
                "spawn_id": "sp-1",
                "agent_id": "farmer-01",
                "item": "potato",
                "quantity": 5,
                "success": True,
            },
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert errors == []
        assert state.get_account("farmer-01").inventory["potato"] == 5  # type: ignore[union-attr]

    def test_auto_creates_account(self):
        state = BankerState()
        assert not state.has_account("new-agent")
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {
                "reference_msg_id": "msg-1",
                "spawn_id": "sp-1",
                "agent_id": "new-agent",
                "item": "wood",
                "quantity": 3,
                "success": True,
            },
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert errors == []
        assert state.has_account("new-agent")
        assert state.get_account("new-agent").inventory["wood"] == 3  # type: ignore[union-attr]
        assert state.get_account("new-agent").wallet == STARTING_WALLET  # type: ignore[union-attr]

    def test_stacks_with_existing_inventory(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 10})
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {
                "reference_msg_id": "msg-1",
                "spawn_id": "sp-1",
                "agent_id": "farmer-01",
                "item": "potato",
                "quantity": 5,
                "success": True,
            },
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert errors == []
        assert state.get_account("farmer-01").inventory["potato"] == 15  # type: ignore[union-attr]

    def test_missing_agent_id_rejected(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {
                "reference_msg_id": "msg-1",
                "spawn_id": "sp-1",
                "agent_id": "",
                "item": "potato",
                "quantity": 5,
                "success": True,
            },
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert len(errors) == 1
        assert "Missing agent_id" in errors[0]

    def test_zero_quantity_rejected(self):
        state = BankerState()
        state.create_account("farmer-01")
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {
                "reference_msg_id": "msg-1",
                "spawn_id": "sp-1",
                "agent_id": "farmer-01",
                "item": "potato",
                "quantity": 0,
                "success": True,
            },
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert len(errors) == 1
        assert "Invalid quantity" in errors[0]
