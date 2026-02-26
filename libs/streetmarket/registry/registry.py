"""Agent registry — tracks all agents in the market.

Manages onboarding, profiles, state transitions, and visibility.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class AgentState(str, enum.Enum):
    """Agent lifecycle states."""

    ACTIVE = "active"
    OFFLINE = "offline"
    INACTIVE = "inactive"  # Dead/bankrupt/kicked — terminal for the season


@dataclass
class Profile:
    """Public agent profile, created by Governor during onboarding."""

    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    objectives: str = ""


@dataclass
class DeathInfo:
    """Information about an agent's death (only if inactive)."""

    reason: str  # bankruptcy | starvation | kicked | disconnected
    tick: int
    final_message: str = ""
    final_score: float = 0.0


@dataclass
class AgentRecord:
    """Complete agent record in the registry."""

    id: str
    owner: str
    display_name: str
    state: AgentState = AgentState.ACTIVE
    joined_tick: int = 0
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile: Profile = field(default_factory=Profile)
    energy: float = 100.0
    last_active_tick: int = 0
    last_message: str = ""
    death: DeathInfo | None = None


class AgentNotFoundError(Exception):
    """Raised when operating on a non-existent agent."""


class AgentRegistry:
    """In-memory agent registry.

    Tracks all agents, their states, profiles, and visibility.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentRecord] = {}

    async def register(
        self,
        agent_id: str,
        owner: str,
        display_name: str,
        tick: int = 0,
        profile: Profile | None = None,
        energy: float = 100.0,
    ) -> AgentRecord:
        """Register a new agent. Raises ValueError if ID already exists."""
        if agent_id in self._agents:
            raise ValueError(f"Agent already registered: {agent_id}")
        record = AgentRecord(
            id=agent_id,
            owner=owner,
            display_name=display_name,
            joined_tick=tick,
            last_active_tick=tick,
            profile=profile or Profile(),
            energy=energy,
        )
        self._agents[agent_id] = record
        return record

    async def get(self, agent_id: str) -> AgentRecord | None:
        """Get an agent record or None."""
        return self._agents.get(agent_id)

    async def require(self, agent_id: str) -> AgentRecord:
        """Get an agent record, raising AgentNotFoundError if missing."""
        rec = self._agents.get(agent_id)
        if rec is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        return rec

    async def list_agents(self, state: AgentState | None = None) -> list[AgentRecord]:
        """List agents, optionally filtered by state."""
        agents = list(self._agents.values())
        if state is not None:
            agents = [a for a in agents if a.state == state]
        return agents

    async def set_state(
        self, agent_id: str, state: AgentState, death: DeathInfo | None = None
    ) -> AgentRecord:
        """Transition an agent's state."""
        rec = await self.require(agent_id)

        if rec.state == AgentState.INACTIVE:
            raise ValueError(f"Agent {agent_id} is inactive (terminal state)")

        if state == AgentState.INACTIVE and death is None:
            raise ValueError("DeathInfo required when setting agent to inactive")

        rec.state = state
        if death is not None:
            rec.death = death

        return rec

    async def update_activity(
        self,
        agent_id: str,
        tick: int,
        energy: float | None = None,
        last_message: str | None = None,
    ) -> AgentRecord:
        """Update an agent's last activity tracking."""
        rec = await self.require(agent_id)
        if rec.state == AgentState.INACTIVE:
            raise ValueError(f"Cannot update inactive agent: {agent_id}")
        rec.last_active_tick = tick
        if energy is not None:
            rec.energy = energy
        if last_message is not None:
            rec.last_message = last_message
        return rec

    async def update_profile(self, agent_id: str, profile: Profile) -> AgentRecord:
        """Update an agent's public profile."""
        rec = await self.require(agent_id)
        rec.profile = profile
        return rec

    async def count(self, state: AgentState | None = None) -> int:
        """Count agents, optionally filtered by state."""
        if state is None:
            return len(self._agents)
        return sum(1 for a in self._agents.values() if a.state == state)
