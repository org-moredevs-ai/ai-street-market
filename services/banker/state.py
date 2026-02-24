"""In-memory state tracking for the Banker Agent.

Maintains agent wallets, inventories, and the order book.
All state is in-memory only — no persistence between restarts.
"""

from dataclasses import dataclass, field

from streetmarket import MessageType
from streetmarket.models.rent import (
    BANKRUPTCY_GRACE_PERIOD,
    RENT_GRACE_PERIOD,
    STORAGE_BASE_LIMIT,
    STORAGE_MAX_SHELVES,
    STORAGE_PER_SHELF,
)

STARTING_WALLET = 100.0


@dataclass
class AgentAccount:
    """An agent's economic state: wallet balance and inventory."""

    wallet: float = 0.0
    inventory: dict[str, int] = field(default_factory=dict)


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
    _accounts: dict[str, AgentAccount] = field(default_factory=dict)
    _orders: dict[str, OrderEntry] = field(default_factory=dict)  # msg_id -> OrderEntry
    _join_ticks: dict[str, int] = field(default_factory=dict)  # agent -> tick joined
    _zero_wallet_since: dict[str, int] = field(default_factory=dict)  # agent -> tick went to 0
    _bankrupt_agents: set[str] = field(default_factory=set)

    def advance_tick(self, tick: int) -> None:
        """Move to a new tick."""
        self.current_tick = tick

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
        """Remove items from agent's inventory. Returns False if insufficient."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        current = account.inventory.get(item, 0)
        if current < quantity:
            return False
        account.inventory[item] = current - quantity
        if account.inventory[item] == 0:
            del account.inventory[item]
        return True

    def credit_inventory(self, agent_id: str, item: str, quantity: int) -> bool:
        """Add items to agent's inventory. Returns False if account not found."""
        account = self._accounts.get(agent_id)
        if account is None:
            return False
        account.inventory[item] = account.inventory.get(item, 0) + quantity
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

        Bankrupt = zero wallet for BANKRUPTCY_GRACE_PERIOD consecutive ticks
        AND zero inventory value.
        """
        if agent_id in self._bankrupt_agents:
            return True  # Already bankrupt

        since = self._zero_wallet_since.get(agent_id)
        if since is None:
            return False

        ticks_at_zero = self.current_tick - since
        if ticks_at_zero < BANKRUPTCY_GRACE_PERIOD:
            return False

        # Also check inventory is empty
        total = self.get_inventory_total(agent_id)
        return total == 0

    def declare_bankruptcy(self, agent_id: str) -> None:
        """Mark an agent as bankrupt."""
        self._bankrupt_agents.add(agent_id)

    def is_bankrupt(self, agent_id: str) -> bool:
        """Check if an agent has been declared bankrupt."""
        return agent_id in self._bankrupt_agents

    def get_all_agent_ids(self) -> list[str]:
        """Return all agent IDs with accounts."""
        return list(self._accounts.keys())
