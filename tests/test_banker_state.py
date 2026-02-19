"""Tests for Banker in-memory state tracking."""

from streetmarket import MessageType

from services.banker.state import (
    STARTING_WALLET,
    BankerState,
    OrderEntry,
)


class TestTickAdvancement:
    def test_advance_tick_updates_current_tick(self):
        state = BankerState()
        state.advance_tick(5)
        assert state.current_tick == 5

    def test_initial_tick_is_zero(self):
        state = BankerState()
        assert state.current_tick == 0


class TestAccountCreation:
    def test_create_account_with_default_wallet(self):
        state = BankerState()
        state.create_account("farmer-01")
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.wallet == STARTING_WALLET

    def test_create_account_with_custom_wallet(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.wallet == 50.0

    def test_has_account_true(self):
        state = BankerState()
        state.create_account("farmer-01")
        assert state.has_account("farmer-01")

    def test_has_account_false(self):
        state = BankerState()
        assert not state.has_account("farmer-01")

    def test_get_account_returns_none_for_unknown(self):
        state = BankerState()
        assert state.get_account("unknown") is None

    def test_new_account_has_empty_inventory(self):
        state = BankerState()
        state.create_account("farmer-01")
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.inventory == {}

    def test_create_account_overwrites_existing(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        state.create_account("farmer-01", wallet=200.0)
        account = state.get_account("farmer-01")
        assert account is not None
        assert account.wallet == 200.0


class TestWalletOperations:
    def test_debit_wallet_success(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=100.0)
        assert state.debit_wallet("farmer-01", 30.0)
        assert state.get_account("farmer-01").wallet == 70.0  # type: ignore[union-attr]

    def test_debit_wallet_insufficient_funds(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=10.0)
        assert not state.debit_wallet("farmer-01", 20.0)
        assert state.get_account("farmer-01").wallet == 10.0  # type: ignore[union-attr]

    def test_debit_wallet_exact_balance(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        assert state.debit_wallet("farmer-01", 50.0)
        assert state.get_account("farmer-01").wallet == 0.0  # type: ignore[union-attr]

    def test_debit_wallet_unknown_account(self):
        state = BankerState()
        assert not state.debit_wallet("unknown", 10.0)

    def test_credit_wallet_success(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        assert state.credit_wallet("farmer-01", 30.0)
        assert state.get_account("farmer-01").wallet == 80.0  # type: ignore[union-attr]

    def test_credit_wallet_unknown_account(self):
        state = BankerState()
        assert not state.credit_wallet("unknown", 10.0)


class TestInventoryOperations:
    def test_credit_inventory_success(self):
        state = BankerState()
        state.create_account("farmer-01")
        assert state.credit_inventory("farmer-01", "potato", 5)
        assert state.get_account("farmer-01").inventory == {"potato": 5}  # type: ignore[union-attr]

    def test_credit_inventory_stacks(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 3)
        state.credit_inventory("farmer-01", "potato", 2)
        assert state.get_account("farmer-01").inventory["potato"] == 5  # type: ignore[union-attr]

    def test_credit_inventory_unknown_account(self):
        state = BankerState()
        assert not state.credit_inventory("unknown", "potato", 5)

    def test_debit_inventory_success(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5)
        assert state.debit_inventory("farmer-01", "potato", 3)
        assert state.get_account("farmer-01").inventory["potato"] == 2  # type: ignore[union-attr]

    def test_debit_inventory_exact_amount_removes_key(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5)
        assert state.debit_inventory("farmer-01", "potato", 5)
        assert "potato" not in state.get_account("farmer-01").inventory  # type: ignore[union-attr]

    def test_debit_inventory_insufficient(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 2)
        assert not state.debit_inventory("farmer-01", "potato", 5)
        # Inventory unchanged
        assert state.get_account("farmer-01").inventory["potato"] == 2  # type: ignore[union-attr]

    def test_debit_inventory_unknown_account(self):
        state = BankerState()
        assert not state.debit_inventory("unknown", "potato", 1)

    def test_debit_inventory_missing_item(self):
        state = BankerState()
        state.create_account("farmer-01")
        assert not state.debit_inventory("farmer-01", "potato", 1)

    def test_has_inventory_true(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5)
        assert state.has_inventory("farmer-01", "potato", 3)

    def test_has_inventory_exact(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 5)
        assert state.has_inventory("farmer-01", "potato", 5)

    def test_has_inventory_insufficient(self):
        state = BankerState()
        state.create_account("farmer-01")
        state.credit_inventory("farmer-01", "potato", 2)
        assert not state.has_inventory("farmer-01", "potato", 5)

    def test_has_inventory_unknown_account(self):
        state = BankerState()
        assert not state.has_inventory("unknown", "potato", 1)

    def test_has_inventory_missing_item(self):
        state = BankerState()
        state.create_account("farmer-01")
        assert not state.has_inventory("farmer-01", "potato", 1)


class TestOrderBook:
    def _make_order(
        self,
        msg_id: str = "order-1",
        from_agent: str = "farmer-01",
        msg_type: MessageType = MessageType.OFFER,
        item: str = "potato",
        quantity: int = 10,
        price: float = 3.0,
        tick: int = 1,
        expires_tick: int | None = None,
    ) -> OrderEntry:
        return OrderEntry(
            msg_id=msg_id,
            from_agent=from_agent,
            msg_type=msg_type,
            item=item,
            quantity=quantity,
            price_per_unit=price,
            tick=tick,
            expires_tick=expires_tick,
        )

    def test_add_and_get_order(self):
        state = BankerState()
        order = self._make_order()
        state.add_order(order)
        assert state.get_order("order-1") is order

    def test_get_order_missing(self):
        state = BankerState()
        assert state.get_order("nonexistent") is None

    def test_remove_order(self):
        state = BankerState()
        order = self._make_order()
        state.add_order(order)
        removed = state.remove_order("order-1")
        assert removed is order
        assert state.get_order("order-1") is None

    def test_remove_order_missing(self):
        state = BankerState()
        assert state.remove_order("nonexistent") is None

    def test_reduce_order_partial(self):
        state = BankerState()
        order = self._make_order(quantity=10)
        state.add_order(order)
        state.reduce_order("order-1", 3)
        remaining = state.get_order("order-1")
        assert remaining is not None
        assert remaining.quantity == 7

    def test_reduce_order_to_zero_removes(self):
        state = BankerState()
        order = self._make_order(quantity=5)
        state.add_order(order)
        state.reduce_order("order-1", 5)
        assert state.get_order("order-1") is None

    def test_reduce_order_below_zero_removes(self):
        state = BankerState()
        order = self._make_order(quantity=3)
        state.add_order(order)
        state.reduce_order("order-1", 10)
        assert state.get_order("order-1") is None

    def test_order_count(self):
        state = BankerState()
        assert state.order_count() == 0
        state.add_order(self._make_order(msg_id="o1"))
        state.add_order(self._make_order(msg_id="o2"))
        assert state.order_count() == 2

    def test_purge_expired_orders(self):
        state = BankerState()
        state.advance_tick(5)
        state.add_order(self._make_order(msg_id="expired", expires_tick=5))
        state.add_order(self._make_order(msg_id="active", expires_tick=10))
        state.add_order(self._make_order(msg_id="no-expiry"))
        expired = state.purge_expired_orders()
        assert len(expired) == 1
        assert expired[0].msg_id == "expired"
        assert state.order_count() == 2

    def test_purge_expired_removes_past_ticks(self):
        state = BankerState()
        state.advance_tick(10)
        state.add_order(self._make_order(msg_id="old", expires_tick=3))
        expired = state.purge_expired_orders()
        assert len(expired) == 1

    def test_purge_no_expired(self):
        state = BankerState()
        state.advance_tick(1)
        state.add_order(self._make_order(msg_id="active", expires_tick=10))
        expired = state.purge_expired_orders()
        assert len(expired) == 0
        assert state.order_count() == 1
