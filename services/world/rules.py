"""World Engine rules — pure functions for tick, gather, and energy logic."""

import logging

from streetmarket import Envelope
from streetmarket.models.energy import (
    ACTION_ENERGY_COSTS,
    REGEN_PER_TICK,
    SHELTER_BONUS_REGEN,
)

from services.world.state import WorldState

logger = logging.getLogger(__name__)


def process_tick(state: WorldState) -> tuple[int, str, dict[str, int]]:
    """Advance tick and create a new spawn pool.

    Returns (tick_number, spawn_id, items_dict).
    """
    tick = state.advance_tick()
    pool = state.create_spawn()
    return tick, pool.spawn_id, dict(pool.remaining)


def process_gather(
    envelope: Envelope, state: WorldState
) -> tuple[int, bool, str | None]:
    """Validate and execute a FCFS gather request.

    Returns (granted_quantity, success, reason).
    """
    spawn_id = envelope.payload.get("spawn_id", "")
    item = envelope.payload.get("item", "")
    quantity = envelope.payload.get("quantity", 0)

    if not spawn_id:
        return 0, False, "Missing spawn_id"

    if not item:
        return 0, False, "Missing item"

    if quantity <= 0:
        return 0, False, "Quantity must be positive"

    granted, error = state.try_gather(spawn_id, item, quantity)

    if error is not None:
        return 0, False, error

    reason = None
    if granted < quantity:
        reason = f"Partial: only {granted} remaining"

    return granted, True, reason


def check_gather_energy(agent_id: str, state: WorldState) -> str | None:
    """Check if an agent has enough energy to gather.

    Returns None if OK, or an error reason string.
    """
    cost = ACTION_ENERGY_COSTS.get("gather", 0.0)
    current = state.get_energy(agent_id)
    if current < cost:
        return f"Insufficient energy: has {current:.1f}, needs {cost:.1f}"
    return None


def deduct_gather_energy(agent_id: str, state: WorldState) -> None:
    """Deduct energy cost for a gather action."""
    cost = ACTION_ENERGY_COSTS.get("gather", 0.0)
    state.deduct_energy(agent_id, cost)


def apply_regen(state: WorldState) -> dict[str, float]:
    """Apply per-tick energy regen to all agents.

    Returns dict of agent_id -> new energy after regen.
    Bankrupt agents are excluded — they stay at 0.
    """
    result: dict[str, float] = {}
    for agent_id in list(state.get_all_energy().keys()):
        if state.is_bankrupt(agent_id):
            result[agent_id] = 0.0
            continue
        regen = REGEN_PER_TICK
        if state.is_sheltered(agent_id):
            regen += SHELTER_BONUS_REGEN
        new_val = state.add_energy(agent_id, regen)
        result[agent_id] = new_val
    return result


def get_energy_cost(action_type: str) -> float:
    """Get the energy cost for a given action type."""
    return ACTION_ENERGY_COSTS.get(action_type, 0.0)


def process_consume_result(
    agent_id: str, energy_restored: float, state: WorldState
) -> float:
    """Apply energy restoration from consuming an item.

    Returns the new energy value.
    """
    return state.add_energy(agent_id, energy_restored)
