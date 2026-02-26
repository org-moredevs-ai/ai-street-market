"""Tests for Banker economic validation rules."""

from streetmarket import Envelope, MessageType

from services.banker.rules import (
    RentResultData,
    check_all_bankruptcies,
    process_accept,
    process_bid,
    process_consume,
    process_craft_complete,
    process_craft_start,
    process_gather_result,
    process_join,
    process_offer,
    process_rent,
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


class TestProcessConsume:
    def test_successful_consume(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"soup": 3})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert result.errors == []
        assert result.agent_id == "farmer-01"
        assert result.item == "soup"
        assert result.quantity == 1
        assert result.energy_restored == 30.0
        # Soup debited
        assert state.get_account("farmer-01").inventory.get("soup", 0) == 2  # type: ignore[union-attr]

    def test_consume_multiple(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"soup": 5})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 2},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert result.errors == []
        assert result.energy_restored == 60.0  # 30 * 2
        assert state.get_account("farmer-01").inventory.get("soup", 0) == 3  # type: ignore[union-attr]

    def test_consume_no_account(self):
        state = BankerState()
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="unknown-agent",
        )
        result = process_consume(env, state)
        assert len(result.errors) == 1
        assert "No account" in result.errors[0]

    def test_consume_insufficient_inventory(self):
        state = BankerState()
        state.create_account("farmer-01")  # No soup
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert len(result.errors) == 1
        assert "insufficient" in result.errors[0]

    def test_consume_non_consumable_item(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"potato": 10})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "potato", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert len(result.errors) == 1
        assert "no energy_restore" in result.errors[0]
        # Inventory not debited
        assert state.get_account("farmer-01").inventory["potato"] == 10  # type: ignore[union-attr]

    def test_consume_unknown_item(self):
        state = BankerState()
        state.create_account("farmer-01")
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "diamond", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert len(result.errors) == 1
        # Either "insufficient" or "Unknown item" depending on order of checks
        assert result.errors[0]  # Some error exists

    def test_consume_last_item(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"soup": 1})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert result.errors == []
        assert state.get_account("farmer-01").inventory.get("soup", 0) == 0  # type: ignore[union-attr]

    def test_consume_stores_reference_msg_id(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"soup": 1})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup", "quantity": 1},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert result.reference_msg_id == env.id

    def test_consume_default_quantity_one(self):
        state = BankerState()
        _setup_agent_with_inventory(state, "farmer-01", {"soup": 2})
        env = _make_envelope(
            MessageType.CONSUME,
            {"item": "soup"},
            from_agent="farmer-01",
        )
        result = process_consume(env, state)
        assert result.errors == []
        assert result.quantity == 1


# ---------------------------------------------------------------------------
# BF-3: Rent confiscation
# ---------------------------------------------------------------------------


class TestRentConfiscation:
    """BF-3: When wallet=0, confiscate inventory at fire-sale prices."""

    def test_confiscate_cheapest_items_first(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=0.0)
        state.credit_inventory("farmer-01", "onion", 10)  # base_price 2.0
        state.credit_inventory("farmer-01", "wood", 5)    # base_price 3.0
        state._join_ticks["farmer-01"] = 1

        result = process_rent("farmer-01", state)
        # Rent = 0.5, wallet = 0, so confiscation kicks in
        assert result.confiscated_items is not None
        # Cheapest = nails(1.0) but farmer has onion(2.0) and wood(3.0)
        # Onion confiscation price = 2.0 * 0.70 = 1.40
        # 1 onion covers 1.40 >= 0.50 debt
        assert "onion" in result.confiscated_items
        assert result.confiscated_items["onion"] == 1

    def test_confiscation_30_percent_deductible(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=0.0)
        state.credit_inventory("farmer-01", "potato", 100)
        state._join_ticks["farmer-01"] = 1

        # Record a settlement price of 3.0 per potato
        state.record_settlement_price("potato", 3.0)
        conf_price = state.get_confiscation_price("potato")
        assert conf_price == 3.0 * 0.70  # 2.10

    def test_round_up_to_whole_units(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=0.0)
        # Stone base price = 4.0, confiscation = 2.80
        # Rent = 0.5, need ceil(0.5 / 2.80) = 1 unit
        state.credit_inventory("farmer-01", "stone", 5)
        state._join_ticks["farmer-01"] = 1

        result = process_rent("farmer-01", state)
        assert result.confiscated_items is not None
        assert result.confiscated_items.get("stone") == 1

    def test_multiple_item_types_confiscated(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=0.0)
        # Very cheap items to force multi-item confiscation
        # Record very low settlement prices
        state.record_settlement_price("nails", 0.10)
        state.credit_inventory("farmer-01", "nails", 2)
        state.credit_inventory("farmer-01", "potato", 10)
        state._join_ticks["farmer-01"] = 1

        result = process_rent("farmer-01", state)
        assert result.confiscated_items is not None
        # nails confiscation = 0.10 * 0.70 = 0.07 per unit
        # 2 nails = 0.14, not enough for 0.5 rent
        # Then potato at base 2.0 * 0.70 = 1.40
        # 1 potato covers remainder
        total_items = sum(result.confiscated_items.values())
        assert total_items >= 2  # At least nails + potato

    def test_falls_back_to_base_price_no_settlements(self):
        state = BankerState(current_tick=60)
        # No settlement prices recorded — should use base_price
        price = state.get_confiscation_price("potato")
        assert price == 2.0 * 0.70  # base_price * (1 - 0.30)

    def test_remaining_debt_when_inventory_runs_out(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=0.0)
        # Very low value items — 1 nail at confiscation price 0.07
        state.record_settlement_price("nails", 0.10)
        state.credit_inventory("farmer-01", "nails", 1)
        state._join_ticks["farmer-01"] = 1

        result = process_rent("farmer-01", state)
        # 1 nail at 0.07 can't cover 0.5 rent
        assert result.confiscated_items is not None
        assert result.confiscated_items["nails"] == 1
        # Agent should still have zero wallet tracked
        assert state.get_zero_wallet_since("farmer-01") > 0

    def test_no_confiscation_when_wallet_covers_rent(self):
        state = BankerState(current_tick=60)
        state.create_account("farmer-01", wallet=10.0)
        state.credit_inventory("farmer-01", "potato", 50)
        state._join_ticks["farmer-01"] = 1

        result = process_rent("farmer-01", state)
        assert result.confiscated_items is None
        assert result.amount == 0.5


# ---------------------------------------------------------------------------
# Spoilage — Banker state batch tracking
# ---------------------------------------------------------------------------


class TestBankerSpoilage:
    """Phase 1: Batch tracking and spoilage in BankerState."""

    def test_credit_with_tick_creates_batch(self):
        state = BankerState(current_tick=10)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5, tick=10)
        account = state.get_account("farmer-01")
        assert account is not None
        assert len(account._batches) == 1
        assert account._batches[0].item == "potato"
        assert account._batches[0].quantity == 5
        assert account._batches[0].created_tick == 10

    def test_non_perishable_no_batch(self):
        state = BankerState(current_tick=10)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "wood", 5, tick=10)
        account = state.get_account("farmer-01")
        assert account is not None
        assert len(account._batches) == 0

    def test_debit_inventory_fifo(self):
        state = BankerState(current_tick=10)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 3, tick=5)
        state.credit_inventory("farmer-01", "potato", 5, tick=8)
        # Debit 4 — should consume all 3 from batch 1 and 1 from batch 2
        state.debit_inventory("farmer-01", "potato", 4)
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.inventory["potato"] == 4
        # Only batch from tick 8 should remain, with qty=4
        assert len(account._batches) == 1
        assert account._batches[0].created_tick == 8
        assert account._batches[0].quantity == 4

    def test_process_spoilage_removes_expired(self):
        state = BankerState(current_tick=110)  # potato spoils at 100 ticks
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5, tick=5)  # age = 105 > 100
        results = state.process_spoilage()
        assert len(results) == 1
        assert results[0].agent_id == "farmer-01"
        assert results[0].item == "potato"
        assert results[0].quantity == 5
        assert state.get_account("farmer-01").inventory.get("potato", 0) == 0  # type: ignore

    def test_process_spoilage_keeps_fresh(self):
        state = BankerState(current_tick=50)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5, tick=10)  # age = 40 < 100
        results = state.process_spoilage()
        assert len(results) == 0
        assert state.get_account("farmer-01").inventory.get("potato", 0) == 5  # type: ignore

    def test_process_spoilage_partial_batches(self):
        state = BankerState(current_tick=110)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 3, tick=5)   # age 105 > 100 → spoils
        state.credit_inventory("farmer-01", "potato", 5, tick=50)  # age 60 < 100 → fresh
        results = state.process_spoilage()
        assert len(results) == 1
        assert results[0].quantity == 3
        assert state.get_account("farmer-01").inventory.get("potato", 0) == 5  # type: ignore

    def test_non_perishable_never_spoils(self):
        state = BankerState(current_tick=9999)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "wood", 10, tick=1)
        results = state.process_spoilage()
        assert len(results) == 0
        assert state.get_account("farmer-01").inventory.get("wood", 0) == 10  # type: ignore

    def test_backward_compat_credit_without_tick(self):
        state = BankerState(current_tick=10)
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5)  # no tick
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.inventory["potato"] == 5
        assert len(account._batches) == 0  # no batch created
