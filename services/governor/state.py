"""In-memory state tracking for the Governor Agent."""

from dataclasses import dataclass, field

MAX_ACTIONS_PER_TICK = 5
HEARTBEAT_TIMEOUT_TICKS = 10


@dataclass
class ActiveCraft:
    """Tracks an in-progress crafting operation."""

    recipe: str
    started_tick: int
    estimated_ticks: int


@dataclass
class GovernorState:
    """Tracks per-tick actions, heartbeats, and active crafts.

    All state is in-memory only — no persistence between restarts.
    """

    current_tick: int = 0
    _actions_this_tick: dict[str, int] = field(default_factory=dict)
    _last_heartbeat_tick: dict[str, int] = field(default_factory=dict)
    _active_crafts: dict[str, ActiveCraft] = field(default_factory=dict)
    _known_agents: set[str] = field(default_factory=set)

    def advance_tick(self, tick: int) -> None:
        """Move to a new tick and reset per-tick counters."""
        self.current_tick = tick
        self._actions_this_tick.clear()

    def record_action(self, agent_id: str) -> None:
        """Record that an agent performed an action this tick."""
        self._actions_this_tick[agent_id] = self._actions_this_tick.get(agent_id, 0) + 1

    def get_action_count(self, agent_id: str) -> int:
        """Get how many actions an agent has taken this tick."""
        return self._actions_this_tick.get(agent_id, 0)

    def is_rate_limited(self, agent_id: str) -> bool:
        """Check if an agent has exceeded the per-tick action limit."""
        return self.get_action_count(agent_id) >= MAX_ACTIONS_PER_TICK

    def record_heartbeat(self, agent_id: str) -> None:
        """Record that an agent sent a heartbeat."""
        self._last_heartbeat_tick[agent_id] = self.current_tick

    def is_inactive(self, agent_id: str) -> bool:
        """Check if an agent has missed too many heartbeat ticks.

        Returns False for agents that have never sent a heartbeat
        (they might be newly joined).
        """
        if agent_id not in self._last_heartbeat_tick:
            return False
        ticks_since = self.current_tick - self._last_heartbeat_tick[agent_id]
        return ticks_since > HEARTBEAT_TIMEOUT_TICKS

    def register_agent(self, agent_id: str) -> None:
        """Register an agent as known (from a join message)."""
        self._known_agents.add(agent_id)

    def is_known_agent(self, agent_id: str) -> bool:
        """Check if an agent has joined."""
        return agent_id in self._known_agents

    def start_craft(self, agent_id: str, recipe: str, estimated_ticks: int) -> None:
        """Record that an agent started crafting."""
        self._active_crafts[agent_id] = ActiveCraft(
            recipe=recipe,
            started_tick=self.current_tick,
            estimated_ticks=estimated_ticks,
        )

    def complete_craft(self, agent_id: str) -> ActiveCraft | None:
        """Remove and return an agent's active craft, or None if not crafting."""
        return self._active_crafts.pop(agent_id, None)

    def is_crafting(self, agent_id: str) -> bool:
        """Check if an agent is currently crafting."""
        return agent_id in self._active_crafts

    def get_active_craft(self, agent_id: str) -> ActiveCraft | None:
        """Get an agent's active craft, or None."""
        return self._active_crafts.get(agent_id)
