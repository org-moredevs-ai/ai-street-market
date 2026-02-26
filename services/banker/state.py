"""In-memory state tracking for the Banker Agent.

Maintains agent wallets, inventories, and the order book.
All state is in-memory only — no persistence between restarts.
"""

import math
from dataclasses import dataclass, field

from streetmarket import MessageType
from streetmarket.models.catalogue import ITEMS, PERISHABLE_ITEMS
from streetmarket.models.rent import (
    BANKRUPTCY_GRACE_PERIOD,
    RENT_GRACE_PERIOD,
    STORAGE_BASE_LIMIT,
    STORAGE_MAX_SHELVES,
    STORAGE_PER_SHELF,
)

STARTING_WALLET = 100.0
CONFISCATION_DEDUCTIBLE = 0.30  # 30% deducted from fire-sale price


@dataclass
class InventoryBatch:
    """A batch of perishable items with a creation tick for spoilage tracking."""

    item: str
    quantity: int
    created_tick: int
    spoil_ticks: int  # from catalogue — how long before spoilage


@dataclass
class SpoilageResult:
    """Result of a single spoilage event."""

    agent_id: str
    item: str
    quantity: int


@dataclass
class ConfiscationResult:
    """Result of a rent confiscation."""

    confiscated_items: dict[str, int]  # item → qty seized
    debt_covered: float  # how much debt was covered


@dataclass
class AgentAccount:
    """An agent's economic state: wallet balance and inventory."""

    wallet: float = 0.0
    inventory: dict[str, int] = field(default_factory=dict)
    _batches: list[InventoryBatch] = field(default_factory=list)


@dataclass
class OrderEntry:
    """A live offer or bid in the order book."""

    msg_id: str
    from_agent: str
    msg_type: MessageType  # OFFER or BID
    item: str
    quantity: int
    price_per_unit: float  # offer.price_per_unit or bid.max_price_per_unit
    tick: int
    expires_tick: int | None = None


@dataclass
class TradeResult:
    """Result of attempting to settle a trade (from process_accept)."""

    errors: list[str] = field(default_factory=list)
    buyer: str = ""
    seller: str = ""
    item: str = ""
    quantity: int = 0
    total_price: float = 0.0
    reference_msg_id: str = ""


@dataclass
class BankerState:
    """Tracks accounts and the order book for the Banker Agent."""

    current_tick: int = 0
    town_treasury: float = 0.0
    total_rent_collected: float = 0.0
    _accounts: dict[str, AgentAccount] = field(default_factory=dict)
    _orders: dict[str, OrderEntry] = field(default_factory=dict)  # msg_id -> OrderEntry
    _join_ticks: dict[str, int] = field(default_factory=dict)  # agent -> tick joined
    _zero_wallet_since: dict[str, int] = field(default_factory=dict)  # agent -> tick went to 0
    _bankrupt_agents: set[str] = field(default_factory=set)
    _min_settlement_prices: dict[str, float] = field(default_factory=dict)  # item -> lowest price

    def advance_tick(self, tick: int) -> bool:
        """Move to a new tick.

        Returns False if the tick is not strictly greater than the current tick
        (protects against stale messages from previous runs).
        """
        if tick <= self.current_tick:
            return False
        self.current_tick = tick
        return True

    # --- Account operations ---

    def create_account(self, agent_id: str, wallet: float = STARTING_WALLET) -> None:
        """Create a new account with the given starting wallet."""
        self._accounts[agent_id] = AgentAccount(wallet=wallet)

    def has_account(self, agent_id: str) -> bool:
        """Check if an agent has a registered account."""
        return agent_id in self._accounts

    def get_account(self, agent_id: str) -> AgentAccount | None:
        """Get an agent's account, or None if not registered."""
        return self._accounts.get(agent_id)

    # --- Wallet operations ---

    def debit_wallet(self, agent_id: str, amount: float) -> bool:
        """Subtract amount from agent's wallet. Returns False if insufficient funds."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        if account.wallet < amount:
            return False
        account.wallet -= amount
        return True

    def credit_wallet(self, agent_id: str, amount: float) -> bool:
        """Add amount to agent's wallet. Returns False if account not found."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        account.wallet += amount
        return True

    # --- Inventory operations ---

    def debit_inventory(self, agent_id: str, item: str, quantity: int) -> bool:
        """Remove items from agent's inventory. Returns False if insufficient.

        Consumes FIFO from oldest batches (perishable items).
        """
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        current = account.inventory.get(item, 0)
        if current < quantity:
            return False
        account.inventory[item] = current - quantity
        if account.inventory[item] == 0:
            del account.inventory[item]
        # FIFO: consume from oldest batches first
        remaining = quantity
        new_batches: list[InventoryBatch] = []
        for batch in account._batches:
            if batch.item != item or remaining <= 0:
                new_batches.append(batch)
                continue
            if batch.quantity <= remaining:
                remaining -= batch.quantity
                # batch fully consumed — skip it
            else:
                batch.quantity -= remaining
                remaining = 0
                new_batches.append(batch)
        account._batches = new_batches
        return True

    def credit_inventory(
        self, agent_id: str, item: str, quantity: int, *, tick: int | None = None,
    ) -> bool:
        """Add items to agent's inventory. Returns False if account not found.

        If tick is provided and the item is perishable, creates a batch for spoilage tracking.
        """
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        account.inventory[item] = account.inventory.get(item, 0) + quantity
        # Track batch for perishable items
        if tick is not None and item in PERISHABLE_ITEMS:
            account._batches.append(
                InventoryBatch(
                    item=item,
                    quantity=quantity,
                    created_tick=tick,
                    spoil_ticks=PERISHABLE_ITEMS[item],
                )
            )
        return True

    def has_inventory(self, agent_id: str, item: str, quantity: int) -> bool:
        """Check if agent has at least `quantity` of `item`."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        return account.inventory.get(item, 0) >= quantity

    # --- Order book operations ---

    def add_order(self, order: OrderEntry) -> None:
        """Add an order to the book."""
        self._orders[order.msg_id] = order

    def get_order(self, msg_id: str) -> OrderEntry | None:
        """Look up an order by its message ID."""
        return self._orders.get(msg_id)

    def remove_order(self, msg_id: str) -> OrderEntry | None:
        """Remove and return an order from the book."""
        return self._orders.pop(msg_id, None)

    def reduce_order(self, msg_id: str, quantity: int) -> None:
        """Reduce an order's quantity. Removes it if quantity reaches zero."""
        order = self._orders.get(msg_id)
        if order is not None:
            order.quantity -= quantity
            if order.quantity <= 0:
                del self._orders[msg_id]

    def purge_expired_orders(self, max_age_ticks: int = 20) -> list[OrderEntry]:
        """Remove expired and stale orders. Returns removed orders.

        Removes orders that either:
        - Have an explicit expires_tick <= current_tick, or
        - Are older than max_age_ticks (prevents unbounded growth)
        """
        expired: list[OrderEntry] = []
        to_remove: list[str] = []
        for msg_id, order in self._orders.items():
            if order.expires_tick is not None and order.expires_tick <= self.current_tick:
                expired.append(order)
                to_remove.append(msg_id)
            elif (self.current_tick - order.tick) > max_age_ticks:
                expired.append(order)
                to_remove.append(msg_id)
        for msg_id in to_remove:
            del self._orders[msg_id]
        return expired

    def order_count(self) -> int:
        """Return the number of orders in the book."""
        return len(self._orders)

    # --- Storage operations ---

    def get_inventory_total(self, agent_id: str) -> int:
        """Return the total number of items in an agent's inventory."""
        account = self._accounts.get(agent_id)
        if account is None:
            return 0
        return sum(account.inventory.values())

    def get_storage_limit(self, agent_id: str) -> int:
        """Return the agent's storage limit (base + shelves consumed)."""
        account = self._accounts.get(agent_id)
        if account is None:
            return STORAGE_BASE_LIMIT
        shelves = min(account.inventory.get("shelf", 0), STORAGE_MAX_SHELVES)
        return STORAGE_BASE_LIMIT + shelves * STORAGE_PER_SHELF

    def is_over_storage_limit(self, agent_id: str) -> bool:
        """Check if an agent's inventory exceeds storage limit."""
        return self.get_inventory_total(agent_id) > self.get_storage_limit(agent_id)

    def would_exceed_storage(self, agent_id: str, additional: int) -> bool:
        """Check if adding items would exceed storage limit."""
        return (self.get_inventory_total(agent_id) + additional) > self.get_storage_limit(agent_id)

    # --- Join tick tracking (for rent grace period) ---

    def record_join_tick(self, agent_id: str) -> None:
        """Record the tick when an agent joined."""
        if agent_id not in self._join_ticks:
            self._join_ticks[agent_id] = self.current_tick

    def get_join_tick(self, agent_id: str) -> int | None:
        """Get the tick when an agent joined, or None."""
        return self._join_ticks.get(agent_id)

    def is_in_grace_period(self, agent_id: str) -> bool:
        """Check if an agent is still in the rent grace period."""
        join_tick = self._join_ticks.get(agent_id)
        if join_tick is None:
            return True  # Unknown join = assume grace
        return (self.current_tick - join_tick) < RENT_GRACE_PERIOD

    def has_house(self, agent_id: str) -> bool:
        """Check if an agent owns a house (rent exempt)."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        return account.inventory.get("house", 0) > 0

    # --- Bankruptcy tracking ---

    def record_zero_wallet(self, agent_id: str) -> None:
        """Record that an agent's wallet hit zero this tick."""
        if agent_id not in self._zero_wallet_since:
            self._zero_wallet_since[agent_id] = self.current_tick

    def clear_zero_wallet(self, agent_id: str) -> None:
        """Clear zero-wallet tracking (agent got money back)."""
        self._zero_wallet_since.pop(agent_id, None)

    def get_zero_wallet_since(self, agent_id: str) -> int:
        """Get the tick when an agent's wallet first hit zero, or 0 if not tracked."""
        return self._zero_wallet_since.get(agent_id, 0)

    def check_bankruptcy(self, agent_id: str) -> bool:
        """Check if an agent should be declared bankrupt.

        Bankrupt = zero wallet for BANKRUPTCY_GRACE_PERIOD consecutive ticks.
        Inventory doesn't prevent bankruptcy — it gets liquidated.
        In real economics, insolvency = can't pay debts regardless of assets.
        """
        if agent_id in self._bankrupt_agents:
            return True  # Already bankrupt

        since = self._zero_wallet_since.get(agent_id)
        if since is None:
            return False

        ticks_at_zero = self.current_tick - since
        return ticks_at_zero >= BANKRUPTCY_GRACE_PERIOD

    def declare_bankruptcy(self, agent_id: str) -> None:
        """Mark an agent as bankrupt."""
        self._bankrupt_agents.add(agent_id)

    def is_bankrupt(self, agent_id: str) -> bool:
        """Check if an agent has been declared bankrupt."""
        return agent_id in self._bankrupt_agents

    # --- Settlement price tracking (for confiscation) ---

    def record_settlement_price(self, item: str, price_per_unit: float) -> None:
        """Track the lowest settlement price for an item (used in confiscation)."""
        current_min = self._min_settlement_prices.get(item)
        if current_min is None or price_per_unit < current_min:
            self._min_settlement_prices[item] = price_per_unit

    def get_confiscation_price(self, item: str) -> float:
        """Get the fire-sale price for an item (lowest settlement or base_price × 0.70)."""
        min_price = self._min_settlement_prices.get(item)
        if min_price is None:
            cat_item = ITEMS.get(item)
            base = cat_item.base_price if cat_item else 1.0
            return base * (1.0 - CONFISCATION_DEDUCTIBLE)
        return min_price * (1.0 - CONFISCATION_DEDUCTIBLE)

    def confiscate_for_rent(self, agent_id: str, debt: float) -> ConfiscationResult:
        """Confiscate inventory items to cover unpaid rent.

        Takes cheapest items first. Returns what was confiscated.
        """
        result = ConfiscationResult(confiscated_items={}, debt_covered=0.0)
        account = self._accounts.get(agent_id)
        if account is None or debt <= 0:
            return result

        remaining_debt = debt

        # Build list of (item, confiscation_price) sorted by price ascending (cheapest first)
        item_prices: list[tuple[str, float]] = []
        for item, qty in account.inventory.items():
            if qty > 0:
                item_prices.append((item, self.get_confiscation_price(item)))
        item_prices.sort(key=lambda x: x[1])

        for item, conf_price in item_prices:
            if remaining_debt <= 0:
                break
            available = account.inventory.get(item, 0)
            if available <= 0 or conf_price <= 0:
                continue
            units_needed = math.ceil(remaining_debt / conf_price)
            units_to_take = min(units_needed, available)
            # Remove from inventory
            self.debit_inventory(agent_id, item, units_to_take)
            value_covered = units_to_take * conf_price
            remaining_debt -= value_covered
            result.confiscated_items[item] = (
                result.confiscated_items.get(item, 0) + units_to_take
            )
            result.debt_covered += value_covered

        # Credit the covered debt to treasury
        covered = min(debt, result.debt_covered)
        self.town_treasury += covered
        self.total_rent_collected += covered

        return result

    # --- Spoilage processing ---

    def process_spoilage(self) -> list[SpoilageResult]:
        """Remove expired batches from all accounts. Returns list of spoilage events."""
        results: list[SpoilageResult] = []
        for agent_id, account in self._accounts.items():
            if agent_id in self._bankrupt_agents:
                continue
            new_batches: list[InventoryBatch] = []
            spoiled: dict[str, int] = {}
            for batch in account._batches:
                age = self.current_tick - batch.created_tick
                if age >= batch.spoil_ticks:
                    spoiled[batch.item] = spoiled.get(batch.item, 0) + batch.quantity
                else:
                    new_batches.append(batch)
            account._batches = new_batches
            # Remove spoiled items from inventory
            for item, qty in spoiled.items():
                current = account.inventory.get(item, 0)
                remove = min(qty, current)
                if remove > 0:
                    account.inventory[item] = current - remove
                    if account.inventory[item] == 0:
                        del account.inventory[item]
                    results.append(SpoilageResult(
                        agent_id=agent_id, item=item, quantity=remove,
                    ))
        return results

    def get_all_agent_ids(self) -> list[str]:
        """Return all agent IDs with accounts."""
        return list(self._accounts.keys())

    def all_agents_bankrupt(self) -> bool:
        """Return True if every registered agent is bankrupt.

        Returns False if no agents have registered yet.
        """
        if not self._accounts:
            return False
        return all(
            agent_id in self._bankrupt_agents
            for agent_id in self._accounts
        )
