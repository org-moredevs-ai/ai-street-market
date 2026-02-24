"""BridgeState — maintains aggregate state so new viewers get a snapshot on connect.

Tracks agents, energy, wallets, prices, narrations, nature events, crafts, and
bankruptcies. Each event handler updates the relevant slice of state.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class AgentInfo:
    """Information about an agent that joined the economy."""

    agent_id: str
    name: str
    description: str
    joined_tick: int


@dataclass
class PriceRecord:
    """A single settlement price observation."""

    item: str
    price_per_unit: float
    quantity: int
    tick: int
    buyer: str
    seller: str


PRICE_HISTORY_LIMIT = 20
CRAFT_HISTORY_LIMIT = 20
DERIVED_PRICE_WINDOW = 5


@dataclass
class BridgeState:
    """Aggregate state for WebSocket snapshot delivery.

    Updated incrementally by NATS message handlers. New WebSocket clients
    receive `get_snapshot()` immediately on connect.
    """

    current_tick: int = 0
    active_agents: dict[str, AgentInfo] = field(default_factory=dict)
    energy_levels: dict[str, float] = field(default_factory=dict)
    agent_wallets: dict[str, float] = field(default_factory=dict)
    recent_prices: dict[str, deque[PriceRecord]] = field(default_factory=dict)
    active_nature_events: list[dict] = field(default_factory=list)
    market_weather: str = "stable"
    latest_narration: dict | None = None
    bankrupt_agents: set[str] = field(default_factory=set)
    agent_last_seen: dict[str, int] = field(default_factory=dict)
    recent_crafts: deque[dict] = field(default_factory=lambda: deque(maxlen=CRAFT_HISTORY_LIMIT))

    # ── Event handlers ──────────────────────────────────────────────────

    def on_tick(self, tick: int) -> None:
        """Update the current tick."""
        self.current_tick = tick

    def on_join(self, payload: dict, tick: int) -> None:
        """Register a new agent."""
        agent_id = payload.get("agent_id", "")
        self.active_agents[agent_id] = AgentInfo(
            agent_id=agent_id,
            name=payload.get("name", agent_id),
            description=payload.get("description", ""),
            joined_tick=tick,
        )
        self.agent_last_seen[agent_id] = tick

    def on_energy_update(self, payload: dict) -> None:
        """Overwrite all energy levels."""
        levels = payload.get("energy_levels", {})
        self.energy_levels = dict(levels)

    def on_settlement(self, payload: dict, tick: int) -> None:
        """Record a trade settlement and update price history."""
        item = payload.get("item", "")
        quantity = payload.get("quantity", 0)
        total_price = payload.get("total_price", 0.0)
        buyer = payload.get("buyer", "")
        seller = payload.get("seller", "")
        price_per_unit = total_price / quantity if quantity > 0 else 0.0

        if item not in self.recent_prices:
            self.recent_prices[item] = deque(maxlen=PRICE_HISTORY_LIMIT)

        self.recent_prices[item].append(
            PriceRecord(
                item=item,
                price_per_unit=price_per_unit,
                quantity=quantity,
                tick=tick,
                buyer=buyer,
                seller=seller,
            )
        )

    def on_narration(self, payload: dict) -> None:
        """Store the latest narration and update market weather."""
        self.latest_narration = dict(payload)
        weather = payload.get("weather", "stable")
        self.market_weather = weather

    def on_nature_event(self, payload: dict) -> None:
        """Track active nature events."""
        self.active_nature_events.append(dict(payload))

    def on_bankruptcy(self, payload: dict) -> None:
        """Mark an agent as bankrupt."""
        agent_id = payload.get("agent_id", "")
        self.bankrupt_agents.add(agent_id)

    def on_rent_due(self, payload: dict) -> None:
        """Update agent wallet from rent deduction."""
        agent_id = payload.get("agent_id", "")
        wallet_after = payload.get("wallet_after", 0.0)
        self.agent_wallets[agent_id] = wallet_after

    def on_heartbeat(self, payload: dict, tick: int) -> None:
        """Update agent last-seen tick and wallet from heartbeat."""
        agent_id = payload.get("agent_id", "")
        self.agent_last_seen[agent_id] = tick
        wallet = payload.get("wallet")
        if wallet is not None:
            self.agent_wallets[agent_id] = wallet

    def on_craft_complete(self, payload: dict) -> None:
        """Record a craft completion in the ring buffer."""
        self.recent_crafts.append(dict(payload))

    # ── Snapshot ────────────────────────────────────────────────────────

    def get_snapshot(self) -> dict:
        """Return the full aggregate state as a JSON-serializable dict."""
        return {
            "current_tick": self.current_tick,
            "active_agents": {
                aid: {
                    "agent_id": info.agent_id,
                    "name": info.name,
                    "description": info.description,
                    "joined_tick": info.joined_tick,
                }
                for aid, info in self.active_agents.items()
            },
            "energy_levels": dict(self.energy_levels),
            "agent_wallets": dict(self.agent_wallets),
            "recent_prices": {
                item: [
                    {
                        "item": r.item,
                        "price_per_unit": r.price_per_unit,
                        "quantity": r.quantity,
                        "tick": r.tick,
                        "buyer": r.buyer,
                        "seller": r.seller,
                    }
                    for r in records
                ]
                for item, records in self.recent_prices.items()
            },
            "derived_prices": self.get_derived_prices(),
            "active_nature_events": list(self.active_nature_events),
            "market_weather": self.market_weather,
            "latest_narration": self.latest_narration,
            "bankrupt_agents": sorted(self.bankrupt_agents),
            "agent_last_seen": dict(self.agent_last_seen),
            "recent_crafts": list(self.recent_crafts),
        }

    def get_derived_prices(self) -> dict[str, float]:
        """Compute weighted average price from last N settlements per item.

        Uses the most recent DERIVED_PRICE_WINDOW records for each item,
        weighted by quantity.
        """
        result: dict[str, float] = {}
        for item, records in self.recent_prices.items():
            recent = list(records)[-DERIVED_PRICE_WINDOW:]
            if not recent:
                continue
            total_value = sum(r.price_per_unit * r.quantity for r in recent)
            total_qty = sum(r.quantity for r in recent)
            if total_qty > 0:
                result[item] = round(total_value / total_qty, 2)
        return result
