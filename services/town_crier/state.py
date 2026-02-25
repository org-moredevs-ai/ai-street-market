"""TownCrierState — accumulates market events between narration windows.

Tracks settlements, bankruptcies, nature events, energy levels, crafts,
joins, and per-agent activity. Computes market weather deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from streetmarket.models.catalogue import ITEMS
from streetmarket.models.messages import MarketWeather

# Narration interval in ticks — every 5 ticks (~25 seconds)
NARRATION_INTERVAL = 5


@dataclass
class SettlementRecord:
    """A single trade settlement."""

    buyer: str
    seller: str
    item: str
    quantity: int
    total_price: float


@dataclass
class CraftRecord:
    """A single crafting completion."""

    agent_id: str
    recipe: str
    output: str
    quantity: int


@dataclass
class RentRecord:
    """A single rent payment."""

    agent_id: str
    amount: float
    wallet_after: float


@dataclass
class TownCrierState:
    """Accumulates events within a narration window.

    Call reset_window() after each narration to clear per-window data
    while preserving all-time statistics and the current tick.
    """

    # Current tick
    current_tick: int = 0
    window_start_tick: int = 0

    # Per-window accumulators
    settlements: list[SettlementRecord] = field(default_factory=list)
    bankruptcies: list[str] = field(default_factory=list)
    nature_events: list[dict[str, str]] = field(default_factory=list)
    rent_payments: list[RentRecord] = field(default_factory=list)
    crafts: list[CraftRecord] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    activity_counts: dict[str, int] = field(default_factory=dict)

    # Snapshot (overwritten each update)
    energy_levels: dict[str, float] = field(default_factory=dict)

    # All-time stats (survive reset_window)
    total_settlements: int = 0
    total_crafts: int = 0
    total_coins_traded: float = 0.0
    all_time_crafts: dict[str, int] = field(default_factory=dict)

    def advance_tick(self, tick: int) -> None:
        """Update the current tick."""
        self.current_tick = tick

    def record_settlement(
        self,
        buyer: str,
        seller: str,
        item: str,
        quantity: int,
        total_price: float,
    ) -> None:
        """Track a completed trade."""
        self.settlements.append(
            SettlementRecord(
                buyer=buyer,
                seller=seller,
                item=item,
                quantity=quantity,
                total_price=total_price,
            )
        )
        self.total_settlements += 1
        self.total_coins_traded += total_price

    def record_bankruptcy(self, agent_id: str) -> None:
        """Track a bankruptcy declaration."""
        self.bankruptcies.append(agent_id)

    def record_nature_event(self, title: str, description: str) -> None:
        """Track a nature event."""
        self.nature_events.append({"title": title, "description": description})

    def update_energy(self, levels: dict[str, float]) -> None:
        """Overwrite the energy snapshot."""
        self.energy_levels = dict(levels)

    def record_rent(self, agent_id: str, amount: float, wallet_after: float) -> None:
        """Track a rent payment."""
        self.rent_payments.append(
            RentRecord(agent_id=agent_id, amount=amount, wallet_after=wallet_after)
        )

    def record_activity(self, agent_id: str) -> None:
        """Count a per-agent action."""
        self.activity_counts[agent_id] = self.activity_counts.get(agent_id, 0) + 1

    def record_join(self, agent_id: str) -> None:
        """Track a new agent joining."""
        self.joins.append(agent_id)

    def record_craft(self, agent_id: str, recipe: str, output: str, quantity: int = 1) -> None:
        """Track a crafting completion."""
        self.crafts.append(
            CraftRecord(agent_id=agent_id, recipe=recipe, output=output, quantity=quantity)
        )
        self.total_crafts += 1
        self.all_time_crafts[recipe] = self.all_time_crafts.get(recipe, 0) + 1

    def should_narrate(self, tick: int) -> bool:
        """Check if it's time to publish a narration."""
        return tick > 0 and tick % NARRATION_INTERVAL == 0

    def compute_market_weather(self) -> MarketWeather:
        """Deterministic market weather classification.

        Algorithm:
        1. bankrupt_count >= 2 or majority agents stressed → CRISIS
        2. Large price variance in settlements (>2x spread from base) → CHAOTIC
        3. stressed_count >= 2 or avg energy < 40 → STRESSED
        4. High trade volume and avg energy > 60 → BOOMING
        5. Default → STABLE
        """
        bankrupt_count = len(self.bankruptcies)

        # Energy analysis
        energy_values = list(self.energy_levels.values())
        avg_energy = (
            sum(energy_values) / len(energy_values) if energy_values else 50.0
        )
        stressed_count = sum(1 for e in energy_values if e < 30)
        agent_count = len(energy_values) if energy_values else 1

        # 1. CRISIS: multiple bankruptcies or majority agents stressed
        if bankrupt_count >= 2:
            return MarketWeather.CRISIS
        if agent_count > 0 and stressed_count > agent_count / 2:
            return MarketWeather.CRISIS

        # 2. CHAOTIC: large price variance
        if len(self.settlements) >= 2:
            prices_by_item: dict[str, list[float]] = {}
            for s in self.settlements:
                ppu = s.total_price / s.quantity if s.quantity > 0 else 0
                prices_by_item.setdefault(s.item, []).append(ppu)

            for item, prices in prices_by_item.items():
                if len(prices) < 2:
                    continue
                min_p, max_p = min(prices), max(prices)
                base_price = ITEMS.get(item)
                base = base_price.base_price if base_price else 1.0
                if min_p > 0 and max_p / min_p > 2.0:
                    return MarketWeather.CHAOTIC
                if base > 0 and (max_p > base * 3 or min_p < base * 0.3):
                    return MarketWeather.CHAOTIC

        # 3. STRESSED: several agents stressed or low avg energy
        if stressed_count >= 2:
            return MarketWeather.STRESSED
        if avg_energy < 40:
            return MarketWeather.STRESSED

        # 4. BOOMING: high trade volume and good energy
        if len(self.settlements) >= 3 and avg_energy > 60:
            return MarketWeather.BOOMING

        # 5. Default
        return MarketWeather.STABLE

    def get_window_summary(self) -> dict:
        """Return all accumulated data for the narrator."""
        return {
            "window_start_tick": self.window_start_tick,
            "window_end_tick": self.current_tick,
            "settlements": [
                {
                    "buyer": s.buyer,
                    "seller": s.seller,
                    "item": s.item,
                    "quantity": s.quantity,
                    "total_price": s.total_price,
                }
                for s in self.settlements
            ],
            "bankruptcies": list(self.bankruptcies),
            "nature_events": list(self.nature_events),
            "energy_levels": dict(self.energy_levels),
            "rent_payments": [
                {
                    "agent_id": r.agent_id,
                    "amount": r.amount,
                    "wallet_after": r.wallet_after,
                }
                for r in self.rent_payments
            ],
            "crafts": [
                {
                    "agent_id": c.agent_id,
                    "recipe": c.recipe,
                    "output": c.output,
                    "quantity": c.quantity,
                }
                for c in self.crafts
            ],
            "joins": list(self.joins),
            "activity_counts": dict(self.activity_counts),
            "weather": self.compute_market_weather(),
            "total_settlements": self.total_settlements,
            "total_crafts": self.total_crafts,
            "total_coins_traded": self.total_coins_traded,
            "all_time_crafts": dict(self.all_time_crafts),
        }

    def reset_window(self) -> None:
        """Clear per-window accumulators. Preserves all-time stats + tick."""
        self.window_start_tick = self.current_tick
        self.settlements.clear()
        self.bankruptcies.clear()
        self.nature_events.clear()
        self.rent_payments.clear()
        self.crafts.clear()
        self.joins.clear()
        self.activity_counts.clear()
