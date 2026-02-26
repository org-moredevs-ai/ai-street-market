"""Tests for the in-memory ledger — wallets, inventory, transactions.

All ledger methods are async. Uses pytest-asyncio with asyncio_mode = "auto".
All monetary values use Decimal for exact arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from streetmarket.ledger.interfaces import (
    LedgerInterface,
    Wallet,
)
from streetmarket.ledger.memory import (
    InMemoryLedger,
    InsufficientFundsError,
    InsufficientItemsError,
    WalletNotFoundError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger() -> InMemoryLedger:
    """Fresh in-memory ledger for each test."""
    return InMemoryLedger()


# ---------------------------------------------------------------------------
# Wallet creation
# ---------------------------------------------------------------------------


async def test_create_wallet(ledger: InMemoryLedger) -> None:
    """Creates wallet with initial balance, verifies balance and total_earned."""
    wallet = await ledger.create_wallet("farmer", Decimal("100"))

    assert isinstance(wallet, Wallet)
    assert wallet.agent_id == "farmer"
    assert wallet.balance == Decimal("100")
    assert wallet.total_earned == Decimal("100")
    assert wallet.total_spent == Decimal("0")
    assert wallet.consecutive_zero_ticks == 0


async def test_create_wallet_duplicate(ledger: InMemoryLedger) -> None:
    """Raises ValueError on duplicate wallet creation."""
    await ledger.create_wallet("farmer", Decimal("50"))

    with pytest.raises(ValueError, match="already exists"):
        await ledger.create_wallet("farmer", Decimal("100"))


# ---------------------------------------------------------------------------
# Wallet retrieval
# ---------------------------------------------------------------------------


async def test_get_wallet_not_found(ledger: InMemoryLedger) -> None:
    """Returns None when wallet does not exist."""
    result = await ledger.get_wallet("ghost")
    assert result is None


async def test_get_balance(ledger: InMemoryLedger) -> None:
    """Returns correct balance for an existing wallet."""
    await ledger.create_wallet("farmer", Decimal("42.5"))
    balance = await ledger.get_balance("farmer")
    assert balance == Decimal("42.5")


async def test_get_balance_not_found(ledger: InMemoryLedger) -> None:
    """Raises WalletNotFoundError when wallet does not exist."""
    with pytest.raises(WalletNotFoundError):
        await ledger.get_balance("ghost")


# ---------------------------------------------------------------------------
# Credit / Debit
# ---------------------------------------------------------------------------


async def test_credit(ledger: InMemoryLedger) -> None:
    """Adds funds and updates total_earned."""
    await ledger.create_wallet("farmer", Decimal("10"))
    await ledger.credit("farmer", Decimal("25"), reason="sold potatoes", tick=1)

    wallet = await ledger.get_wallet("farmer")
    assert wallet is not None
    assert wallet.balance == Decimal("35")
    # total_earned = initial 10 + credit 25
    assert wallet.total_earned == Decimal("35")
    assert wallet.total_spent == Decimal("0")


async def test_credit_negative(ledger: InMemoryLedger) -> None:
    """Raises ValueError when credit amount is non-positive."""
    await ledger.create_wallet("farmer", Decimal("10"))

    with pytest.raises(ValueError, match="positive"):
        await ledger.credit("farmer", Decimal("-5"), reason="bad")

    with pytest.raises(ValueError, match="positive"):
        await ledger.credit("farmer", Decimal("0"), reason="zero")


async def test_debit(ledger: InMemoryLedger) -> None:
    """Removes funds and updates total_spent."""
    await ledger.create_wallet("farmer", Decimal("50"))
    await ledger.debit("farmer", Decimal("20"), reason="bought seeds", tick=1)

    wallet = await ledger.get_wallet("farmer")
    assert wallet is not None
    assert wallet.balance == Decimal("30")
    assert wallet.total_spent == Decimal("20")


async def test_debit_insufficient(ledger: InMemoryLedger) -> None:
    """Raises InsufficientFundsError when balance is too low."""
    await ledger.create_wallet("farmer", Decimal("10"))

    with pytest.raises(InsufficientFundsError):
        await ledger.debit("farmer", Decimal("20"), reason="too expensive")


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


async def test_transfer(ledger: InMemoryLedger) -> None:
    """Moves funds between wallets atomically."""
    await ledger.create_wallet("farmer", Decimal("100"))
    await ledger.create_wallet("chef", Decimal("50"))

    await ledger.transfer("farmer", "chef", Decimal("30"), reason="trade potatoes", tick=1)

    farmer_balance = await ledger.get_balance("farmer")
    chef_balance = await ledger.get_balance("chef")
    assert farmer_balance == Decimal("70")
    assert chef_balance == Decimal("80")

    farmer_wallet = await ledger.get_wallet("farmer")
    chef_wallet = await ledger.get_wallet("chef")
    assert farmer_wallet is not None
    assert chef_wallet is not None
    assert farmer_wallet.total_spent == Decimal("30")
    assert chef_wallet.total_earned == Decimal("80")  # initial 50 + transfer 30


async def test_transfer_insufficient(ledger: InMemoryLedger) -> None:
    """Raises InsufficientFundsError when sender has insufficient balance."""
    await ledger.create_wallet("farmer", Decimal("10"))
    await ledger.create_wallet("chef", Decimal("50"))

    with pytest.raises(InsufficientFundsError):
        await ledger.transfer("farmer", "chef", Decimal("20"), reason="too much")

    # Verify no partial mutation occurred
    assert await ledger.get_balance("farmer") == Decimal("10")
    assert await ledger.get_balance("chef") == Decimal("50")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


async def test_add_item(ledger: InMemoryLedger) -> None:
    """Adds items with batch tracking."""
    await ledger.create_wallet("farmer", Decimal("0"))

    await ledger.add_item("farmer", "potato", 5, tick=1)
    await ledger.add_item("farmer", "potato", 3, tick=2)

    inv = await ledger.get_inventory("farmer")
    assert inv == {"potato": 8}

    # Verify batch tracking internals
    slot = ledger._inventory["farmer"]["potato"]
    assert len(slot.batches) == 2
    assert slot.batches[0].quantity == 5
    assert slot.batches[0].created_tick == 1
    assert slot.batches[1].quantity == 3
    assert slot.batches[1].created_tick == 2


async def test_remove_item_fifo(ledger: InMemoryLedger) -> None:
    """Removes oldest batches first (FIFO)."""
    await ledger.create_wallet("farmer", Decimal("0"))

    await ledger.add_item("farmer", "potato", 3, tick=1)
    await ledger.add_item("farmer", "potato", 5, tick=2)
    await ledger.add_item("farmer", "potato", 2, tick=3)

    # Remove 4 — should consume all of batch 1 (3) + 1 from batch 2
    await ledger.remove_item("farmer", "potato", 4)

    inv = await ledger.get_inventory("farmer")
    assert inv == {"potato": 6}

    slot = ledger._inventory["farmer"]["potato"]
    assert len(slot.batches) == 2
    # First remaining batch should be the remainder of tick=2 batch
    assert slot.batches[0].quantity == 4
    assert slot.batches[0].created_tick == 2
    # Second batch untouched
    assert slot.batches[1].quantity == 2
    assert slot.batches[1].created_tick == 3


async def test_remove_item_insufficient(ledger: InMemoryLedger) -> None:
    """Raises InsufficientItemsError when not enough items."""
    await ledger.create_wallet("farmer", Decimal("0"))
    await ledger.add_item("farmer", "potato", 2, tick=1)

    with pytest.raises(InsufficientItemsError):
        await ledger.remove_item("farmer", "potato", 5)

    # Verify inventory unchanged after failed removal
    inv = await ledger.get_inventory("farmer")
    assert inv == {"potato": 2}


async def test_get_inventory(ledger: InMemoryLedger) -> None:
    """Returns correct {item: qty} dict."""
    await ledger.create_wallet("farmer", Decimal("0"))

    await ledger.add_item("farmer", "potato", 5, tick=1)
    await ledger.add_item("farmer", "onion", 3, tick=1)
    await ledger.add_item("farmer", "potato", 2, tick=2)

    inv = await ledger.get_inventory("farmer")
    assert inv == {"potato": 7, "onion": 3}


async def test_get_inventory_empty(ledger: InMemoryLedger) -> None:
    """Returns empty dict for wallet with no items."""
    await ledger.create_wallet("farmer", Decimal("0"))
    inv = await ledger.get_inventory("farmer")
    assert inv == {}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


async def test_transactions_recorded(ledger: InMemoryLedger) -> None:
    """Credit, debit, and transfer all create transaction records."""
    await ledger.create_wallet("farmer", Decimal("100"))
    await ledger.create_wallet("chef", Decimal("50"))

    await ledger.credit("farmer", Decimal("10"), reason="bonus", tick=1)
    await ledger.debit("farmer", Decimal("5"), reason="fee", tick=2)
    await ledger.transfer("farmer", "chef", Decimal("20"), reason="trade", tick=3)

    farmer_txns = await ledger.get_transactions("farmer")
    assert len(farmer_txns) == 3

    # Credit transaction
    assert farmer_txns[0].type == "credit"
    assert farmer_txns[0].amount == Decimal("10")
    assert farmer_txns[0].tick == 1
    assert farmer_txns[0].details["reason"] == "bonus"

    # Debit transaction
    assert farmer_txns[1].type == "debit"
    assert farmer_txns[1].amount == Decimal("5")
    assert farmer_txns[1].tick == 2

    # Transfer transaction (from farmer side)
    assert farmer_txns[2].type == "trade"
    assert farmer_txns[2].amount == Decimal("20")
    assert farmer_txns[2].counterparty == "chef"
    assert farmer_txns[2].tick == 3

    # Chef should also have a transaction record for the transfer
    chef_txns = await ledger.get_transactions("chef")
    assert len(chef_txns) == 1
    assert chef_txns[0].type == "trade"
    assert chef_txns[0].counterparty == "farmer"


# ---------------------------------------------------------------------------
# Tick zero check (bankruptcy tracking)
# ---------------------------------------------------------------------------


async def test_tick_zero_check_increments(ledger: InMemoryLedger) -> None:
    """Increments consecutive_zero_ticks when balance is zero."""
    await ledger.create_wallet("farmer", Decimal("0"))

    count = await ledger.tick_zero_check("farmer")
    assert count == 1

    count = await ledger.tick_zero_check("farmer")
    assert count == 2

    count = await ledger.tick_zero_check("farmer")
    assert count == 3


async def test_tick_zero_check_resets(ledger: InMemoryLedger) -> None:
    """Resets consecutive_zero_ticks when balance > 0."""
    await ledger.create_wallet("farmer", Decimal("0"))

    # Build up some zero ticks
    await ledger.tick_zero_check("farmer")
    await ledger.tick_zero_check("farmer")
    count = await ledger.tick_zero_check("farmer")
    assert count == 3

    # Credit to make balance positive
    await ledger.credit("farmer", Decimal("10"), reason="donation", tick=5)

    # Now zero check should reset
    count = await ledger.tick_zero_check("farmer")
    assert count == 0

    wallet = await ledger.get_wallet("farmer")
    assert wallet is not None
    assert wallet.consecutive_zero_ticks == 0


# ---------------------------------------------------------------------------
# Aggregate queries
# ---------------------------------------------------------------------------


async def test_get_total_items(ledger: InMemoryLedger) -> None:
    """Counts total items across all inventory slots."""
    await ledger.create_wallet("farmer", Decimal("0"))

    await ledger.add_item("farmer", "potato", 5, tick=1)
    await ledger.add_item("farmer", "onion", 3, tick=1)
    await ledger.add_item("farmer", "wood", 7, tick=2)

    total = await ledger.get_total_items("farmer")
    assert total == 15


async def test_list_wallets(ledger: InMemoryLedger) -> None:
    """Lists all wallets in the ledger."""
    await ledger.create_wallet("farmer", Decimal("100"))
    await ledger.create_wallet("chef", Decimal("50"))
    await ledger.create_wallet("baker", Decimal("75"))

    wallets = await ledger.list_wallets()
    assert len(wallets) == 3

    agent_ids = {w.agent_id for w in wallets}
    assert agent_ids == {"farmer", "chef", "baker"}


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------


async def test_ledger_implements_interface(ledger: InMemoryLedger) -> None:
    """InMemoryLedger satisfies the LedgerInterface protocol (runtime_checkable)."""
    assert isinstance(ledger, LedgerInterface)
