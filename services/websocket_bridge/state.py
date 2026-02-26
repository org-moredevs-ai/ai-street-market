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


@dataclass
class AgentScoreTracker:
    """Per-agent raw counters for social scoring. Resets each economy run."""

    decisions_total: int = 0
    decisions_with_thoughts: int = 0
    decisions_with_speech: int = 0
    moods_seen: set[str] = field(default_factory=set)
    trade_actions: int = 0  # offers + bids + accepts
    settlements: int = 0  # completed trades
    crafts_completed: int = 0
    total_actions: int = 0  # sum of action_count from AGENT_STATUS


PRICE_HISTORY_LIMIT = 20
CRAFT_HISTORY_LIMIT = 20
NARRATION_HISTORY_LIMIT = 20
DERIVED_PRICE_WINDOW = 5
CHATTER_HISTORY_LIMIT = 150
EVENT_HISTORY_LIMIT = 200


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
    narration_history: deque[dict] = field(
        default_factory=lambda: deque(maxlen=NARRATION_HISTORY_LIMIT)
    )
    bankrupt_agents: set[str] = field(default_factory=set)
    agent_last_seen: dict[str, int] = field(default_factory=dict)
    recent_crafts: deque[dict] = field(default_factory=lambda: deque(maxlen=CRAFT_HISTORY_LIMIT))
    # Energy deltas: current - previous per agent
    _previous_energy: dict[str, float] = field(default_factory=dict)
    energy_deltas: dict[str, float] = field(default_factory=dict)
    # Rent / Treasury tracking
    town_treasury: float = 0.0
    total_rent_collected: float = 0.0
    # Inventory counts from heartbeats
    agent_inventories: dict[str, int] = field(default_factory=dict)
    # Detailed inventory breakdown per agent
    agent_inventory_details: dict[str, dict[str, int]] = field(default_factory=dict)
    # Agent status (thoughts, speech, mood) from LLM decisions
    agent_statuses: dict[str, dict] = field(default_factory=dict)
    # Social scoring — raw counters per agent
    agent_score_trackers: dict[str, AgentScoreTracker] = field(default_factory=dict)
    # Spoilage tracking
    recent_spoilage: deque[dict] = field(default_factory=lambda: deque(maxlen=CRAFT_HISTORY_LIMIT))
    # Economy halt
    economy_halted: bool = False
    halt_reason: str = ""
    halt_tick: int = 0
    # Recent chatter for Market page (speech, trades, crafts, etc.)
    recent_chatter: deque[dict] = field(
        default_factory=lambda: deque(maxlen=CHATTER_HISTORY_LIMIT)
    )
    # Recent events for Events page (serialized envelopes)
    recent_events: deque[dict] = field(
        default_factory=lambda: deque(maxlen=EVENT_HISTORY_LIMIT)
    )

    # ── Event handlers ──────────────────────────────────────────────────

    def on_tick(self, tick: int) -> None:
        """Update the current tick and prune expired nature events."""
        if tick > self.current_tick:
            self.current_tick = tick
            # Prune expired nature events
            self.active_nature_events = [
                e for e in self.active_nature_events
                if e.get("end_tick", float("inf")) > tick
            ]

    def on_join(self, payload: dict, tick: int) -> None:
        """Register a new agent."""
        agent_id = payload.get("agent_id", "")
        name = payload.get("name", agent_id)
        self.active_agents[agent_id] = AgentInfo(
            agent_id=agent_id,
            name=name,
            description=payload.get("description", ""),
            joined_tick=tick,
        )
        self.agent_last_seen[agent_id] = tick
        # Initialize wallet to starting amount (Banker grants 100.0 on join)
        if agent_id not in self.agent_wallets:
            self.agent_wallets[agent_id] = 100.0
        self.recent_chatter.append({
            "type": "join", "agent_id": agent_id, "name": name, "tick": tick,
        })

    def on_energy_update(self, payload: dict) -> None:
        """Overwrite all energy levels and compute deltas (skip bankrupt agents)."""
        levels = payload.get("energy_levels", {})
        new_levels = dict(levels)
        # Compute deltas (exclude bankrupt)
        deltas: dict[str, float] = {}
        for agent_id, current in new_levels.items():
            if agent_id in self.bankrupt_agents:
                continue
            previous = self._previous_energy.get(agent_id, current)
            deltas[agent_id] = round(current - previous, 1)
        self.energy_deltas = deltas
        self._previous_energy = dict(new_levels)
        self.energy_levels = new_levels
        # Re-freeze bankrupt agents at zero
        for aid in self.bankrupt_agents:
            self.energy_levels[aid] = 0.0

    def on_settlement(self, payload: dict, tick: int) -> None:
        """Record a trade settlement, update price history and wallets."""
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

        # Update wallets from settlement data (skip bankrupt agents)
        buyer_wallet = payload.get("buyer_wallet_after")
        if buyer_wallet is not None and buyer not in self.bankrupt_agents:
            self.agent_wallets[buyer] = buyer_wallet
        seller_wallet = payload.get("seller_wallet_after")
        if seller_wallet is not None and seller not in self.bankrupt_agents:
            self.agent_wallets[seller] = seller_wallet

        # Update score trackers
        if buyer:
            tracker = self._get_tracker(buyer)
            if tracker:
                tracker.settlements += 1
        if seller:
            tracker = self._get_tracker(seller)
            if tracker:
                tracker.settlements += 1
        self.recent_chatter.append({
            "type": "trade", "buyer": buyer, "seller": seller,
            "item": item, "quantity": quantity, "total_price": total_price, "tick": tick,
        })

    def on_narration(self, payload: dict) -> None:
        """Store the latest narration, append to history, and update market weather."""
        narration = dict(payload)
        self.latest_narration = narration
        self.narration_history.append(narration)
        weather = payload.get("weather", "stable")
        self.market_weather = weather
        self.recent_chatter.append({
            "type": "crier",
            "headline": payload.get("headline", ""),
            "body": payload.get("body", ""),
            "weather": weather,
            "tick": payload.get("window_end_tick", self.current_tick),
        })

    def on_nature_event(self, payload: dict) -> None:
        """Track active nature events with computed end_tick."""
        event = dict(payload)
        duration = event.get("duration_ticks", event.get("remaining_ticks", 0))
        event["end_tick"] = self.current_tick + duration
        self.active_nature_events.append(event)
        self.recent_chatter.append({
            "type": "nature",
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "tick": self.current_tick,
        })

    def on_bankruptcy(self, payload: dict) -> None:
        """Mark an agent as bankrupt and freeze their data."""
        agent_id = payload.get("agent_id", "")
        self.bankrupt_agents.add(agent_id)
        # Freeze wallet and energy at zero
        self.agent_wallets[agent_id] = 0.0
        self.energy_levels[agent_id] = 0.0
        self.recent_chatter.append({
            "type": "bankruptcy", "agent_id": agent_id,
            "reason": payload.get("reason", ""), "tick": self.current_tick,
        })
        # Infer economy halt if all active agents are now bankrupt
        if self.active_agents and self.bankrupt_agents >= set(self.active_agents.keys()):
            self.economy_halted = True
            self.halt_tick = self.current_tick
            self.halt_reason = "All agents bankrupt"

    def on_rent_due(self, payload: dict) -> None:
        """Update agent wallet and treasury from rent deduction."""
        agent_id = payload.get("agent_id", "")
        if agent_id in self.bankrupt_agents:
            return
        wallet_after = payload.get("wallet_after", 0.0)
        self.agent_wallets[agent_id] = wallet_after
        # Track treasury totals from banker
        treasury = payload.get("treasury_balance")
        if treasury is not None:
            self.town_treasury = treasury
        total_rent = payload.get("total_rent_collected")
        if total_rent is not None:
            self.total_rent_collected = total_rent

    def on_heartbeat(self, payload: dict, tick: int) -> None:
        """Update agent last-seen tick, wallet, and inventory from heartbeat."""
        agent_id = payload.get("agent_id", "")
        if agent_id in self.bankrupt_agents:
            return
        self.agent_last_seen[agent_id] = tick
        wallet = payload.get("wallet")
        if wallet is not None:
            self.agent_wallets[agent_id] = wallet
        inventory_count = payload.get("inventory_count")
        if inventory_count is not None:
            self.agent_inventories[agent_id] = inventory_count
        inventory = payload.get("inventory")
        if inventory is not None:
            self.agent_inventory_details[agent_id] = inventory

    def on_agent_status(self, payload: dict, tick: int) -> None:
        """Track the latest agent status (thoughts, speech, mood)."""
        agent_id = payload.get("agent_id", "")
        if agent_id in self.bankrupt_agents:
            return
        speech = payload.get("speech", "")
        thoughts = payload.get("thoughts", "")
        mood = payload.get("mood", "calm")
        self.agent_statuses[agent_id] = {
            "thoughts": thoughts,
            "speech": speech,
            "mood": mood,
            "action_count": payload.get("action_count", 0),
            "tick": tick,
        }
        if speech or thoughts:
            self.recent_chatter.append({
                "type": "speech" if speech else "thought",
                "agent_id": agent_id,
                "speech": speech,
                "thoughts": thoughts,
                "mood": mood,
                "tick": tick,
            })
        # Update score tracker (frozen for bankrupt agents)
        tracker = self._get_tracker(agent_id)
        if tracker:
            tracker.decisions_total += 1
            if thoughts:
                tracker.decisions_with_thoughts += 1
            if speech:
                tracker.decisions_with_speech += 1
            if mood:
                tracker.moods_seen.add(mood)
            tracker.total_actions += payload.get("action_count", 0)

    def on_craft_complete(self, payload: dict) -> None:
        """Record a craft completion in the ring buffer."""
        self.recent_crafts.append(dict(payload))
        agent_id = payload.get("agent_id", payload.get("agent", ""))
        if agent_id:
            tracker = self._get_tracker(agent_id)
            if tracker:
                tracker.crafts_completed += 1
        self.recent_chatter.append({
            "type": "craft", "agent_id": agent_id,
            "recipe": payload.get("recipe", ""),
            "output": payload.get("output", {}),
            "tick": self.current_tick,
        })

    def on_item_spoiled(self, payload: dict) -> None:
        """Record a spoilage event in the ring buffer."""
        self.recent_spoilage.append(dict(payload))
        self.recent_chatter.append({
            "type": "spoilage",
            "agent_id": payload.get("agent_id", ""),
            "item": payload.get("item", ""),
            "quantity": payload.get("quantity", 0),
            "tick": self.current_tick,
        })

    def on_economy_halt(self, payload: dict) -> None:
        """Mark the economy as halted."""
        self.economy_halted = True
        self.halt_reason = payload.get("reason", "All agents bankrupt")
        self.halt_tick = payload.get("final_tick", self.current_tick)

    def on_trade_action(self, agent_id: str) -> None:
        """Increment trade action counter for OFFER/BID/ACCEPT."""
        if agent_id:
            tracker = self._get_tracker(agent_id)
            if tracker:
                tracker.trade_actions += 1

    def _get_tracker(self, agent_id: str) -> AgentScoreTracker | None:
        """Get or create the score tracker for an agent.

        Returns None for bankrupt agents — their scores are frozen.
        """
        if agent_id in self.bankrupt_agents:
            return None
        if agent_id not in self.agent_score_trackers:
            self.agent_score_trackers[agent_id] = AgentScoreTracker()
        return self.agent_score_trackers[agent_id]

    # ── Scoring ────────────────────────────────────────────────────────

    def compute_agent_scores(self) -> dict[str, dict]:
        """Compute social scores for all tracked agents.

        Returns {agent_id: {expressiveness, social, character, trading, total, counters}}.
        Each dimension is 0–100. Total is the average.
        """
        result: dict[str, dict] = {}
        for agent_id, t in self.agent_score_trackers.items():
            if t.decisions_total == 0:
                result[agent_id] = {
                    "expressiveness": 0,
                    "social": 0,
                    "character": 0,
                    "trading": 0,
                    "total": 0,
                    "counters": self._tracker_counters(t),
                }
                continue

            # Expressiveness: max of thoughts rate or speech rate × 100
            thoughts_rate = t.decisions_with_thoughts / t.decisions_total
            speech_rate = t.decisions_with_speech / t.decisions_total
            expressiveness = min(100, round(max(thoughts_rate, speech_rate) * 100))

            # Social: balanced communication — sweet spot 10–90% speech rate
            if t.decisions_with_speech == 0:
                social = 0
            elif speech_rate < 0.1:
                social = round(speech_rate / 0.1 * 50)
            elif speech_rate > 0.9:
                social = round((1.0 - speech_rate) / 0.1 * 50)
            else:
                # Linear from 50 at edges to 100 at center (50%)
                distance_from_center = abs(speech_rate - 0.5)
                social = round(100 - distance_from_center * 125)
                social = max(50, min(100, social))

            # Character: mood variety — 20 points per unique mood, cap at 100
            character = min(100, len(t.moods_seen) * 20)

            # Trading: market participation relative to decisions
            trade_score = (t.trade_actions + t.settlements * 2) / t.decisions_total * 100
            trading = min(100, round(trade_score))

            total = round((expressiveness + social + character + trading) / 4)

            result[agent_id] = {
                "expressiveness": expressiveness,
                "social": social,
                "character": character,
                "trading": trading,
                "total": total,
                "counters": self._tracker_counters(t),
            }
        return result

    @staticmethod
    def _tracker_counters(t: AgentScoreTracker) -> dict:
        """Serialize tracker counters for the snapshot."""
        return {
            "decisions_total": t.decisions_total,
            "decisions_with_thoughts": t.decisions_with_thoughts,
            "decisions_with_speech": t.decisions_with_speech,
            "moods_seen": sorted(t.moods_seen),
            "trade_actions": t.trade_actions,
            "settlements": t.settlements,
            "crafts_completed": t.crafts_completed,
            "total_actions": t.total_actions,
        }

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
            "narrations": list(self.narration_history),
            "bankrupt_agents": sorted(self.bankrupt_agents),
            "agent_last_seen": dict(self.agent_last_seen),
            "recent_crafts": list(self.recent_crafts),
            "energy_deltas": dict(self.energy_deltas),
            "town_treasury": self.town_treasury,
            "total_rent_collected": self.total_rent_collected,
            "agent_inventories": dict(self.agent_inventories),
            "agent_inventory_details": dict(self.agent_inventory_details),
            "agent_statuses": dict(self.agent_statuses),
            "agent_scores": self.compute_agent_scores(),
            "recent_spoilage": list(self.recent_spoilage),
            "economy_halted": self.economy_halted,
            "halt_reason": self.halt_reason,
            "halt_tick": self.halt_tick,
            "recent_chatter": list(self.recent_chatter),
            "recent_events": list(self.recent_events),
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
