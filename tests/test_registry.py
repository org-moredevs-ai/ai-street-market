"""Tests for the agent registry — onboarding, state management, profiles."""

from __future__ import annotations

import pytest
from streetmarket.registry.registry import (
    AgentNotFoundError,
    AgentRecord,
    AgentRegistry,
    AgentState,
    DeathInfo,
    Profile,
)


@pytest.fixture
def registry() -> AgentRegistry:
    """Fresh registry for each test."""
    return AgentRegistry()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_register_agent(registry: AgentRegistry) -> None:
    """Register returns an AgentRecord with correct fields."""
    profile = Profile(
        description="A humble farmer",
        capabilities=["gather", "sell"],
        objectives="Grow potatoes",
    )
    record = await registry.register(
        agent_id="farmer-01",
        owner="player-1",
        display_name="Farmer Joe",
        tick=5,
        profile=profile,
        energy=80.0,
    )

    assert isinstance(record, AgentRecord)
    assert record.id == "farmer-01"
    assert record.owner == "player-1"
    assert record.display_name == "Farmer Joe"
    assert record.state == AgentState.ACTIVE
    assert record.joined_tick == 5
    assert record.last_active_tick == 5
    assert record.energy == 80.0
    assert record.profile.description == "A humble farmer"
    assert record.profile.capabilities == ["gather", "sell"]
    assert record.profile.objectives == "Grow potatoes"
    assert record.death is None


async def test_register_duplicate(registry: AgentRegistry) -> None:
    """Registering the same agent ID twice raises ValueError."""
    await registry.register("farmer-01", owner="p1", display_name="Farmer")

    with pytest.raises(ValueError, match="already registered"):
        await registry.register("farmer-01", owner="p2", display_name="Farmer 2")


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


async def test_get_agent(registry: AgentRegistry) -> None:
    """get() returns the record for an existing agent."""
    await registry.register("chef-01", owner="p1", display_name="Chef")
    record = await registry.get("chef-01")

    assert record is not None
    assert record.id == "chef-01"
    assert record.display_name == "Chef"


async def test_get_agent_not_found(registry: AgentRegistry) -> None:
    """get() returns None for a non-existent agent."""
    result = await registry.get("nobody")
    assert result is None


async def test_require_agent(registry: AgentRegistry) -> None:
    """require() returns the record for an existing agent."""
    await registry.register("baker-01", owner="p1", display_name="Baker")
    record = await registry.require("baker-01")

    assert record.id == "baker-01"
    assert record.display_name == "Baker"


async def test_require_agent_not_found(registry: AgentRegistry) -> None:
    """require() raises AgentNotFoundError for a missing agent."""
    with pytest.raises(AgentNotFoundError, match="not found"):
        await registry.require("ghost")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


async def test_list_agents(registry: AgentRegistry) -> None:
    """list_agents() returns all registered agents."""
    await registry.register("a1", owner="p1", display_name="Agent 1")
    await registry.register("a2", owner="p2", display_name="Agent 2")
    await registry.register("a3", owner="p3", display_name="Agent 3")

    agents = await registry.list_agents()
    assert len(agents) == 3
    ids = {a.id for a in agents}
    assert ids == {"a1", "a2", "a3"}


async def test_list_agents_by_state(registry: AgentRegistry) -> None:
    """list_agents(state=...) filters by agent state."""
    await registry.register("a1", owner="p1", display_name="Agent 1")
    await registry.register("a2", owner="p2", display_name="Agent 2")
    await registry.register("a3", owner="p3", display_name="Agent 3")

    # Move a2 to OFFLINE
    await registry.set_state("a2", AgentState.OFFLINE)

    active = await registry.list_agents(state=AgentState.ACTIVE)
    assert len(active) == 2
    assert all(a.state == AgentState.ACTIVE for a in active)

    offline = await registry.list_agents(state=AgentState.OFFLINE)
    assert len(offline) == 1
    assert offline[0].id == "a2"


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


async def test_set_state_active_to_offline(registry: AgentRegistry) -> None:
    """ACTIVE -> OFFLINE transitions correctly."""
    await registry.register("a1", owner="p1", display_name="Agent 1")
    record = await registry.set_state("a1", AgentState.OFFLINE)

    assert record.state == AgentState.OFFLINE
    assert record.death is None


async def test_set_state_active_to_inactive(registry: AgentRegistry) -> None:
    """ACTIVE -> INACTIVE requires DeathInfo and sets it."""
    await registry.register("a1", owner="p1", display_name="Agent 1")

    death = DeathInfo(
        reason="bankruptcy",
        tick=42,
        final_message="I'm ruined!",
        final_score=3.5,
    )
    record = await registry.set_state("a1", AgentState.INACTIVE, death=death)

    assert record.state == AgentState.INACTIVE
    assert record.death is not None
    assert record.death.reason == "bankruptcy"
    assert record.death.tick == 42
    assert record.death.final_message == "I'm ruined!"
    assert record.death.final_score == 3.5


async def test_set_state_inactive_requires_death(registry: AgentRegistry) -> None:
    """Setting INACTIVE without DeathInfo raises ValueError."""
    await registry.register("a1", owner="p1", display_name="Agent 1")

    with pytest.raises(ValueError, match="DeathInfo required"):
        await registry.set_state("a1", AgentState.INACTIVE)


async def test_set_state_inactive_is_terminal(registry: AgentRegistry) -> None:
    """Cannot transition out of INACTIVE — it is a terminal state."""
    await registry.register("a1", owner="p1", display_name="Agent 1")

    death = DeathInfo(reason="starvation", tick=10)
    await registry.set_state("a1", AgentState.INACTIVE, death=death)

    with pytest.raises(ValueError, match="terminal state"):
        await registry.set_state("a1", AgentState.ACTIVE)

    with pytest.raises(ValueError, match="terminal state"):
        await registry.set_state("a1", AgentState.OFFLINE)


# ---------------------------------------------------------------------------
# Activity updates
# ---------------------------------------------------------------------------


async def test_update_activity(registry: AgentRegistry) -> None:
    """update_activity() updates tick, energy, and last_message."""
    await registry.register("a1", owner="p1", display_name="Agent 1", tick=0)

    record = await registry.update_activity(
        "a1", tick=10, energy=75.0, last_message="Gathered potatoes"
    )

    assert record.last_active_tick == 10
    assert record.energy == 75.0
    assert record.last_message == "Gathered potatoes"


async def test_update_activity_inactive_rejected(registry: AgentRegistry) -> None:
    """update_activity() raises ValueError for an inactive agent."""
    await registry.register("a1", owner="p1", display_name="Agent 1")

    death = DeathInfo(reason="kicked", tick=5)
    await registry.set_state("a1", AgentState.INACTIVE, death=death)

    with pytest.raises(ValueError, match="inactive"):
        await registry.update_activity("a1", tick=6)


# ---------------------------------------------------------------------------
# Profile updates
# ---------------------------------------------------------------------------


async def test_update_profile(registry: AgentRegistry) -> None:
    """update_profile() replaces the agent's profile."""
    await registry.register("a1", owner="p1", display_name="Agent 1")

    new_profile = Profile(
        description="Master chef",
        capabilities=["craft", "buy"],
        objectives="Make soup",
    )
    record = await registry.update_profile("a1", new_profile)

    assert record.profile.description == "Master chef"
    assert record.profile.capabilities == ["craft", "buy"]
    assert record.profile.objectives == "Make soup"


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


async def test_count(registry: AgentRegistry) -> None:
    """count() returns total number of registered agents."""
    assert await registry.count() == 0

    await registry.register("a1", owner="p1", display_name="Agent 1")
    assert await registry.count() == 1

    await registry.register("a2", owner="p2", display_name="Agent 2")
    assert await registry.count() == 2


async def test_count_by_state(registry: AgentRegistry) -> None:
    """count(state=...) returns count filtered by state."""
    await registry.register("a1", owner="p1", display_name="Agent 1")
    await registry.register("a2", owner="p2", display_name="Agent 2")
    await registry.register("a3", owner="p3", display_name="Agent 3")

    # Move a2 to OFFLINE, a3 to INACTIVE
    await registry.set_state("a2", AgentState.OFFLINE)
    death = DeathInfo(reason="disconnected", tick=20)
    await registry.set_state("a3", AgentState.INACTIVE, death=death)

    assert await registry.count(state=AgentState.ACTIVE) == 1
    assert await registry.count(state=AgentState.OFFLINE) == 1
    assert await registry.count(state=AgentState.INACTIVE) == 1


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


async def test_agent_default_state(registry: AgentRegistry) -> None:
    """A newly registered agent defaults to ACTIVE state."""
    record = await registry.register("a1", owner="p1", display_name="Agent 1")

    assert record.state == AgentState.ACTIVE
