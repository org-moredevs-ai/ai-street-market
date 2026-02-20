"""In-memory state for the World Engine.

Tracks the current tick, the active spawn pool, and handles
FCFS resource claiming.
"""

import uuid
from dataclasses import dataclass, field

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


@dataclass
class WorldState:
    """Tracks tick counter and active spawn pool for the World Engine."""

    current_tick: int = 0
    _active_spawn: SpawnPool | None = None
    _spawn_table: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SPAWN_TABLE))

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
        """Create a new spawn pool for the current tick, replacing any previous one."""
        pool = SpawnPool(
            spawn_id=str(uuid.uuid4()),
            tick=self.current_tick,
            remaining=dict(self._spawn_table),
        )
        self._active_spawn = pool
        return pool

    def try_gather(
        self, spawn_id: str, item: str, quantity: int
    ) -> tuple[int, str | None]:
        """Attempt to gather resources from the active spawn pool.

        Returns (granted_quantity, error_or_None).
        Supports partial grants: if pool has fewer than requested, grants what's left.
        """
        if self._active_spawn is None:
            return 0, "No active spawn"

        if self._active_spawn.spawn_id != spawn_id:
            return 0, "Spawn expired or not found"

        available = self._active_spawn.remaining.get(item, 0)
        if available == 0:
            return 0, f"No {item} remaining in spawn"

        granted = min(quantity, available)
        self._active_spawn.remaining[item] = available - granted
        return granted, None
