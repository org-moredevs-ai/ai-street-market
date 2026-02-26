"""In-memory state for the World Engine.

Tracks the current tick, the active spawn pool, energy levels,
and handles FCFS resource claiming.
"""

import uuid
from dataclasses import dataclass, field

from streetmarket.models.energy import MAX_ENERGY, STARTING_ENERGY

DEFAULT_SPAWN_TABLE: dict[str, int] = {
    "potato": 20,
    "onion": 15,
    "wood": 15,
    "nails": 10,
    "stone": 10,
}

DEFAULT_TICK_INTERVAL = 5.0


@dataclass
class SpawnPool:
    """A pool of resources available for one tick."""

    spawn_id: str
    tick: int
    remaining: dict[str, int] = field(default_factory=dict)


# How many ticks a spawn remains valid for gathering.
# With LLM agents (1-3s response time) and 5s tick interval,
# spawns must survive at least 2 ticks to be usable.
SPAWN_TTL = 3


@dataclass
class WorldState:
    """Tracks tick counter, active spawn pool, and energy for the World Engine."""

    current_tick: int = 0
    _active_spawn: SpawnPool | None = None
    _recent_spawns: dict[str, SpawnPool] = field(default_factory=dict)
    _spawn_table: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SPAWN_TABLE))
    _energy: dict[str, float] = field(default_factory=dict)
    _sheltered: set[str] = field(default_factory=set)
    _bankrupt: set[str] = field(default_factory=set)
    _gather_history: list[dict] = field(default_factory=list)

    @property
    def active_spawn(self) -> SpawnPool | None:
        """The currently active spawn pool (None before first tick)."""
        return self._active_spawn

    @property
    def spawn_table(self) -> dict[str, int]:
        """The configured spawn amounts per item."""
        return self._spawn_table

    def advance_tick(self) -> int:
        """Advance to the next tick. Returns the new tick number."""
        self.current_tick += 1
        return self.current_tick

    def create_spawn(self) -> SpawnPool:
        """Create a new spawn pool for the current tick.

        The new pool becomes the active spawn. Old pools are kept
        in _recent_spawns for SPAWN_TTL ticks so LLM agents with
        delayed responses can still gather from them.
        """
        pool = SpawnPool(
            spawn_id=str(uuid.uuid4()),
            tick=self.current_tick,
            remaining=dict(self._spawn_table),
        )
        self._active_spawn = pool
        self._recent_spawns[pool.spawn_id] = pool
        # Expire old spawns
        cutoff = self.current_tick - SPAWN_TTL
        expired = [sid for sid, sp in self._recent_spawns.items() if sp.tick < cutoff]
        for sid in expired:
            del self._recent_spawns[sid]
        return pool

    def try_gather(
        self, spawn_id: str, item: str, quantity: int
    ) -> tuple[int, str | None]:
        """Attempt to gather resources from a spawn pool.

        Returns (granted_quantity, error_or_None).
        Supports partial grants: if pool has fewer than requested, grants what's left.
        Looks up the spawn in recent spawns (TTL-based), not just the latest.
        """
        pool = self._recent_spawns.get(spawn_id)
        if pool is None:
            return 0, "Spawn expired or not found"

        available = pool.remaining.get(item, 0)
        if available == 0:
            return 0, f"No {item} remaining in spawn"

        granted = min(quantity, available)
        pool.remaining[item] = available - granted
        return granted, None

    # --- Energy operations ---

    def register_energy(self, agent_id: str) -> None:
        """Register an agent with starting energy (idempotent)."""
        if agent_id not in self._energy:
            self._energy[agent_id] = STARTING_ENERGY

    def get_energy(self, agent_id: str) -> float:
        """Get an agent's current energy. Returns 0 if unknown."""
        return self._energy.get(agent_id, 0.0)

    def set_energy(self, agent_id: str, value: float) -> None:
        """Set an agent's energy, clamped to [0, MAX_ENERGY]."""
        self._energy[agent_id] = max(0.0, min(value, MAX_ENERGY))

    def deduct_energy(self, agent_id: str, amount: float) -> bool:
        """Deduct energy from an agent. Returns False if insufficient."""
        current = self._energy.get(agent_id, 0.0)
        if current < amount:
            return False
        self._energy[agent_id] = current - amount
        return True

    def add_energy(self, agent_id: str, amount: float) -> float:
        """Add energy to an agent, capped at MAX_ENERGY. Returns new value."""
        current = self._energy.get(agent_id, 0.0)
        new_val = min(current + amount, MAX_ENERGY)
        self._energy[agent_id] = new_val
        return new_val

    def get_all_energy(self) -> dict[str, float]:
        """Return a snapshot of all agent energy levels."""
        return dict(self._energy)

    def set_sheltered(self, agent_id: str, sheltered: bool) -> None:
        """Mark whether an agent has shelter."""
        if sheltered:
            self._sheltered.add(agent_id)
        else:
            self._sheltered.discard(agent_id)

    def is_sheltered(self, agent_id: str) -> bool:
        """Check if an agent has shelter."""
        return agent_id in self._sheltered

    def mark_bankrupt(self, agent_id: str) -> None:
        """Mark an agent as bankrupt — excluded from energy regen/updates."""
        self._bankrupt.add(agent_id)
        # Set energy to 0
        self._energy[agent_id] = 0.0

    def is_bankrupt(self, agent_id: str) -> bool:
        """Check if an agent is bankrupt."""
        return agent_id in self._bankrupt

    # --- Gather history ---

    def record_gather(self, agent_id: str, item: str, quantity: int) -> None:
        """Record a successful gather for nature intelligence context."""
        self._gather_history.append({
            "agent": agent_id,
            "item": item,
            "quantity": quantity,
            "tick": self.current_tick,
        })
        # Keep only last 50
        if len(self._gather_history) > 50:
            self._gather_history = self._gather_history[-50:]

    def get_recent_gathers(self) -> list[dict]:
        """Get the recent gather history."""
        return list(self._gather_history)
