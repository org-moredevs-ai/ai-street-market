"""In-memory ledger implementation.

Exact arithmetic using Decimal. All operations are async for interface
compatibility (future backend swap to DB/blockchain).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from streetmarket.ledger.interfaces import (
    InventoryBatch,
    InventorySlot,
    Transaction,
    Wallet,
)


class InsufficientFundsError(Exception):
    """Raised when a debit exceeds available balance."""


class InsufficientItemsError(Exception):
    """Raised when removing more items than available."""


class WalletNotFoundError(Exception):
    """Raised when operating on a non-existent wallet."""


class InMemoryLedger:
    """In-memory implementation of the deterministic ledger.

    Uses Decimal for exact arithmetic. Thread-safe within a single
    asyncio event loop (no concurrent mutations).
    """

    def __init__(self) -> None:
        self._wallets: dict[str, Wallet] = {}
        self._inventory: dict[str, dict[str, InventorySlot]] = {}
        self._transactions: dict[str, list[Transaction]] = {}

    def _require_wallet(self, agent_id: str) -> Wallet:
        w = self._wallets.get(agent_id)
        if w is None:
            raise WalletNotFoundError(f"No wallet for agent: {agent_id}")
        return w

    async def create_wallet(self, agent_id: str, initial_balance: Decimal) -> Wallet:
        """Create a new wallet with initial balance."""
        if agent_id in self._wallets:
            raise ValueError(f"Wallet already exists for: {agent_id}")
        w = Wallet(agent_id=agent_id, balance=initial_balance, total_earned=initial_balance)
        self._wallets[agent_id] = w
        self._inventory[agent_id] = {}
        self._transactions[agent_id] = []
        return w

    async def get_wallet(self, agent_id: str) -> Wallet | None:
        """Get wallet or None if not found."""
        return self._wallets.get(agent_id)

    async def get_balance(self, agent_id: str) -> Decimal:
        """Get current balance. Raises WalletNotFoundError if not found."""
        return self._require_wallet(agent_id).balance

    async def credit(self, agent_id: str, amount: Decimal, reason: str, tick: int = 0) -> None:
        """Add funds to a wallet."""
        if amount <= 0:
            raise ValueError(f"Credit amount must be positive: {amount}")
        w = self._require_wallet(agent_id)
        w.balance += amount
        w.total_earned += amount
        self._record(agent_id, "credit", amount=amount, tick=tick, details={"reason": reason})

    async def debit(self, agent_id: str, amount: Decimal, reason: str, tick: int = 0) -> None:
        """Remove funds from a wallet. Raises InsufficientFundsError if not enough."""
        if amount <= 0:
            raise ValueError(f"Debit amount must be positive: {amount}")
        w = self._require_wallet(agent_id)
        if w.balance < amount:
            raise InsufficientFundsError(f"{agent_id} has {w.balance}, cannot debit {amount}")
        w.balance -= amount
        w.total_spent += amount
        self._record(agent_id, "debit", amount=amount, tick=tick, details={"reason": reason})

    async def transfer(
        self, from_id: str, to_id: str, amount: Decimal, reason: str, tick: int = 0
    ) -> None:
        """Transfer funds between two wallets atomically."""
        if amount <= 0:
            raise ValueError(f"Transfer amount must be positive: {amount}")
        from_w = self._require_wallet(from_id)
        self._require_wallet(to_id)
        if from_w.balance < amount:
            raise InsufficientFundsError(
                f"{from_id} has {from_w.balance}, cannot transfer {amount}"
            )
        from_w.balance -= amount
        from_w.total_spent += amount
        to_w = self._wallets[to_id]
        to_w.balance += amount
        to_w.total_earned += amount
        self._record(
            from_id,
            "trade",
            amount=amount,
            tick=tick,
            counterparty=to_id,
            details={"reason": reason},
        )
        self._record(
            to_id,
            "trade",
            amount=amount,
            tick=tick,
            counterparty=from_id,
            details={"reason": reason},
        )

    async def get_inventory(self, agent_id: str) -> dict[str, int]:
        """Get inventory as {item: quantity} dict."""
        self._require_wallet(agent_id)
        inv = self._inventory.get(agent_id, {})
        return {item: slot.quantity for item, slot in inv.items() if slot.quantity > 0}

    async def add_item(self, agent_id: str, item: str, qty: int, tick: int = 0) -> None:
        """Add items to inventory with batch tracking."""
        if qty <= 0:
            raise ValueError(f"Quantity must be positive: {qty}")
        self._require_wallet(agent_id)
        inv = self._inventory.setdefault(agent_id, {})
        slot = inv.get(item)
        if slot is None:
            slot = InventorySlot(item=item)
            inv[item] = slot
        slot.quantity += qty
        slot.batches.append(InventoryBatch(quantity=qty, created_tick=tick))

    async def remove_item(self, agent_id: str, item: str, qty: int) -> None:
        """Remove items from inventory (FIFO from oldest batches)."""
        if qty <= 0:
            raise ValueError(f"Quantity must be positive: {qty}")
        self._require_wallet(agent_id)
        inv = self._inventory.get(agent_id, {})
        slot = inv.get(item)
        if slot is None or slot.quantity < qty:
            available = slot.quantity if slot else 0
            raise InsufficientItemsError(f"{agent_id} has {available}x {item}, cannot remove {qty}")
        slot.quantity -= qty
        remaining = qty
        while remaining > 0 and slot.batches:
            batch = slot.batches[0]
            if batch.quantity <= remaining:
                remaining -= batch.quantity
                slot.batches.pop(0)
            else:
                batch.quantity -= remaining
                remaining = 0

    async def get_transactions(self, agent_id: str, limit: int = 50) -> list[Transaction]:
        """Get recent transactions for an agent."""
        txns = self._transactions.get(agent_id, [])
        return txns[-limit:]

    async def tick_zero_check(self, agent_id: str) -> int:
        """Check and update consecutive zero-balance ticks."""
        w = self._require_wallet(agent_id)
        if w.balance == Decimal("0"):
            w.consecutive_zero_ticks += 1
        else:
            w.consecutive_zero_ticks = 0
        return w.consecutive_zero_ticks

    async def get_total_items(self, agent_id: str) -> int:
        """Get total item count across all inventory slots."""
        inv = self._inventory.get(agent_id, {})
        return sum(slot.quantity for slot in inv.values())

    async def list_wallets(self) -> list[Wallet]:
        """List all wallets."""
        return list(self._wallets.values())

    def _record(
        self,
        agent_id: str,
        txn_type: str,
        amount: Decimal = Decimal("0"),
        tick: int = 0,
        counterparty: str = "",
        item: str = "",
        quantity: int = 0,
        details: dict | None = None,
    ) -> None:
        txn = Transaction(
            id=str(uuid.uuid4()),
            tick=tick,
            type=txn_type,
            agent_id=agent_id,
            counterparty=counterparty,
            item=item,
            quantity=quantity,
            amount=amount,
            details=details or {},
        )
        self._transactions.setdefault(agent_id, []).append(txn)
