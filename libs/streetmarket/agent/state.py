"""AgentState — local state mirror for trading agents."""

from dataclasses import dataclass, field


@dataclass
class CraftingJob:
    """An active crafting operation."""

    recipe: str
    started_tick: int
    duration_ticks: int

    @property
    def complete_at_tick(self) -> int:
        return self.started_tick + self.duration_ticks

    def is_done(self, current_tick: int) -> bool:
        return current_tick >= self.complete_at_tick


@dataclass
class PendingOffer:
    """An offer/bid this agent published, awaiting responses."""

    msg_id: str
    item: str
    quantity: int
    price_per_unit: float
    tick: int
    is_sell: bool  # True = offer (selling), False = bid (buying)


@dataclass
class ObservedOffer:
    """An offer or bid from another agent seen this tick."""

    msg_id: str
    from_agent: str
    item: str
    quantity: int
    price_per_unit: float
    is_sell: bool  # True = offer (selling), False = bid (buying)
    tick: int = 0  # Tick when this offer was observed


@dataclass
class AgentState:
    """Optimistic local mirror of the agent's state on the Banker."""

    agent_id: str
    joined: bool = False
    wallet: float = 0.0
    inventory: dict[str, int] = field(default_factory=dict)
    energy: float = 100.0
    current_tick: int = 0
    last_heartbeat_tick: int = 0
    current_spawn_id: str | None = None
    current_spawn_items: dict[str, int] = field(default_factory=dict)
    active_craft: CraftingJob | None = None
    pending_offers: dict[str, PendingOffer] = field(default_factory=dict)
    observed_offers: list[ObservedOffer] = field(default_factory=list)
    actions_this_tick: int = 0
    rent_due_this_tick: float = 0.0
    is_bankrupt: bool = False
    storage_limit: int = 50  # Updated from RENT_DUE messages or shelf count
    price_history: list[dict] = field(default_factory=list)  # Recent settlement prices
    spoiled_this_tick: list[dict] = field(default_factory=list)  # [{item, quantity}]
    confiscated_this_tick: dict[str, int] = field(default_factory=dict)  # item → qty

    # --- Helpers ---

    def inventory_count(self, item: str) -> int:
        """Return the quantity of an item in inventory."""
        return self.inventory.get(item, 0)

    def has_items(self, requirements: dict[str, int]) -> bool:
        """Check if inventory satisfies all requirements."""
        return all(
            self.inventory_count(item) >= qty for item, qty in requirements.items()
        )

    def is_crafting(self) -> bool:
        """Check if there's an active crafting job."""
        return self.active_craft is not None

    def needs_heartbeat(self, interval: int = 5) -> bool:
        """Check if a heartbeat is due (every `interval` ticks)."""
        return self.current_tick - self.last_heartbeat_tick >= interval

    def remaining_actions(self, max_actions: int = 5) -> int:
        """Return how many more actions can be taken this tick."""
        return max(0, max_actions - self.actions_this_tick)

    def add_inventory(self, item: str, quantity: int) -> None:
        """Add items to inventory."""
        self.inventory[item] = self.inventory.get(item, 0) + quantity

    def remove_inventory(self, item: str, quantity: int) -> bool:
        """Remove items from inventory. Returns False if insufficient."""
        current = self.inventory.get(item, 0)
        if current < quantity:
            return False
        self.inventory[item] = current - quantity
        if self.inventory[item] == 0:
            del self.inventory[item]
        return True

    def total_inventory(self) -> int:
        """Return total number of items in inventory."""
        return sum(self.inventory.values())

    def storage_remaining(self) -> int:
        """Return how much storage space is available."""
        return max(0, self.storage_limit - self.total_inventory())

    def advance_tick(self, tick: int) -> None:
        """Advance to a new tick — reset per-tick state."""
        self.current_tick = tick
        self.actions_this_tick = 0
        self.rent_due_this_tick = 0.0
        self.spoiled_this_tick.clear()
        self.confiscated_this_tick.clear()

    def clear_observed_offers(self) -> None:
        """Clear observed offers — call after decide() processes them."""
        self.observed_offers.clear()

    def expire_old_offers(self, max_age: int = 3) -> None:
        """Remove offers older than max_age ticks (keep recent ones)."""
        cutoff = self.current_tick - max_age
        self.observed_offers = [
            o for o in self.observed_offers if o.tick >= cutoff
        ]

    def record_settlement(
        self, item: str, price_per_unit: float, quantity: int
    ) -> None:
        """Record a settlement price for market awareness."""
        self.price_history.append(
            {"item": item, "price": price_per_unit, "qty": quantity}
        )
        # Keep only last 20 settlements
        if len(self.price_history) > 20:
            self.price_history = self.price_history[-20:]
