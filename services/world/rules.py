"""World Engine rules — pure functions for tick and gather logic."""

import logging

from streetmarket import Envelope

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
