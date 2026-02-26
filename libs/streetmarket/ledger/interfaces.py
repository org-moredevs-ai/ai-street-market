"""Ledger interface — protocol classes for the deterministic ledger.

The ledger is behind an interface so the backend can evolve
(in-memory -> SQLite -> PostgreSQL -> blockchain) without changing
any LLM agent code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass
class Wallet:
    """A single agent's wallet."""

    agent_id: str
    balance: Decimal = Decimal("0")
    total_earned: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    consecutive_zero_ticks: int = 0


@dataclass
class InventoryBatch:
    """A batch of items with creation tick for spoilage tracking."""

    quantity: int
    created_tick: int


@dataclass
class InventorySlot:
    """Inventory for a single item type."""

    item: str
    quantity: int = 0
    batches: list[InventoryBatch] = field(default_factory=list)


@dataclass
class Transaction:
    """A recorded transaction."""

    id: str
    tick: int
    type: str  # trade | rent | fine | craft | gather | credit | debit
    agent_id: str
    counterparty: str = ""
    item: str = ""
    quantity: int = 0
    amount: Decimal = Decimal("0")
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LedgerInterface(Protocol):
    """Protocol for the deterministic ledger.

    All monetary operations use Decimal for exact arithmetic.
    """

    async def create_wallet(self, agent_id: str, initial_balance: Decimal) -> Wallet: ...

    async def get_wallet(self, agent_id: str) -> Wallet | None: ...

    async def get_balance(self, agent_id: str) -> Decimal: ...

    async def credit(self, agent_id: str, amount: Decimal, reason: str, tick: int = 0) -> None: ...

    async def debit(self, agent_id: str, amount: Decimal, reason: str, tick: int = 0) -> None: ...

    async def transfer(
        self, from_id: str, to_id: str, amount: Decimal, reason: str, tick: int = 0
    ) -> None: ...

    async def get_inventory(self, agent_id: str) -> dict[str, int]: ...

    async def add_item(self, agent_id: str, item: str, qty: int, tick: int = 0) -> None: ...

    async def remove_item(self, agent_id: str, item: str, qty: int) -> None: ...

    async def get_transactions(self, agent_id: str, limit: int = 50) -> list[Transaction]: ...

    async def tick_zero_check(self, agent_id: str) -> int:
        """Increment consecutive_zero_ticks if balance is 0, reset otherwise.

        Returns the new consecutive_zero_ticks count.
        """
        ...
