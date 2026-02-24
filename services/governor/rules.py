"""Business rule validation — pure functions.

These rules validate market messages against the catalogue, game rules,
and the energy system. No wallet or inventory checks (that's the Banker's job).
"""

from streetmarket import (
    ITEMS,
    RECIPES,
    Envelope,
    MessageType,
    is_valid_item,
    is_valid_recipe,
    validate_message,
)
from streetmarket.models.energy import ACTION_ENERGY_COSTS, FREE_AT_ZERO_ENERGY

from services.governor.state import GovernorState


def validate_envelope_structure(envelope: Envelope) -> list[str]:
    """Validate the structural integrity of an envelope.

    Uses the shared library's validate_message which checks:
    - from_agent is non-empty
    - topic is non-empty
    - type is a known MessageType
    - payload matches the schema for the message type
    """
    return validate_message(envelope)


def validate_business_rules(envelope: Envelope, state: GovernorState) -> list[str]:
    """Validate an envelope against business rules.

    Returns a list of error strings. Empty list means valid.
    Side effects: updates state for join, heartbeat, craft_start, craft_complete.
    """
    errors: list[str] = []
    agent_id = envelope.from_agent
    msg_type = envelope.type

    # Bankruptcy check — bankrupt agents cannot do anything
    if state.is_bankrupt(agent_id):
        return [f"Agent '{agent_id}' is bankrupt and cannot perform actions"]

    # Rate limit check (before recording — checked against actions already taken)
    if state.is_rate_limited(agent_id):
        return [f"Rate limited: {agent_id} exceeded max actions this tick"]

    # Inactive agent check
    if state.is_inactive(agent_id):
        errors.append(f"Agent '{agent_id}' is inactive (no heartbeat)")

    # Energy check — skip for free-at-zero actions
    if msg_type not in FREE_AT_ZERO_ENERGY:
        energy_cost = ACTION_ENERGY_COSTS.get(msg_type, 0.0)
        if energy_cost > 0:
            current_energy = state.get_energy(agent_id)
            if current_energy < energy_cost:
                errors.append(
                    f"Insufficient energy: {agent_id} has {current_energy:.1f}, "
                    f"needs {energy_cost:.1f} for {msg_type}"
                )
                return errors

    # Per-type validation
    if msg_type == MessageType.OFFER:
        errors.extend(_validate_offer(envelope))

    elif msg_type == MessageType.BID:
        errors.extend(_validate_bid(envelope))

    elif msg_type == MessageType.ACCEPT:
        errors.extend(_validate_accept(envelope))

    elif msg_type == MessageType.COUNTER:
        errors.extend(_validate_counter(envelope))

    elif msg_type == MessageType.CRAFT_START:
        errors.extend(_validate_craft_start(envelope, state))

    elif msg_type == MessageType.CRAFT_COMPLETE:
        errors.extend(_validate_craft_complete(envelope, state))

    elif msg_type == MessageType.JOIN:
        _handle_join(envelope, state)

    elif msg_type == MessageType.HEARTBEAT:
        _handle_heartbeat(envelope, state)

    elif msg_type == MessageType.CONSUME:
        errors.extend(_validate_consume(envelope))

    return errors


def _validate_offer(envelope: Envelope) -> list[str]:
    """Offer must reference a valid catalogue item."""
    errors: list[str] = []
    item = envelope.payload.get("item", "")
    if not is_valid_item(item):
        errors.append(f"Unknown item: '{item}'")
    return errors


def _validate_bid(envelope: Envelope) -> list[str]:
    """Bid must reference a valid catalogue item."""
    errors: list[str] = []
    item = envelope.payload.get("item", "")
    if not is_valid_item(item):
        errors.append(f"Unknown item: '{item}'")
    return errors


def _validate_accept(envelope: Envelope) -> list[str]:
    """Accept must have a reference_msg_id."""
    errors: list[str] = []
    ref = envelope.payload.get("reference_msg_id", "")
    if not ref:
        errors.append("Accept missing reference_msg_id")
    return errors


def _validate_counter(envelope: Envelope) -> list[str]:
    """Counter must have a reference_msg_id."""
    errors: list[str] = []
    ref = envelope.payload.get("reference_msg_id", "")
    if not ref:
        errors.append("Counter missing reference_msg_id")
    return errors


def _validate_craft_start(envelope: Envelope, state: GovernorState) -> list[str]:
    """Validate craft_start: recipe exists, inputs match, not already crafting."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    payload = envelope.payload
    recipe_name = payload.get("recipe", "")

    # Recipe must exist
    if not is_valid_recipe(recipe_name):
        errors.append(f"Unknown recipe: '{recipe_name}'")
        return errors

    recipe = RECIPES[recipe_name]

    # Inputs must match recipe
    provided_inputs = payload.get("inputs", {})
    if provided_inputs != recipe.inputs:
        errors.append(
            f"Inputs mismatch for recipe '{recipe_name}': "
            f"expected {recipe.inputs}, got {provided_inputs}"
        )

    # Estimated ticks must match recipe
    estimated = payload.get("estimated_ticks", 0)
    if estimated != recipe.ticks:
        errors.append(
            f"Estimated ticks mismatch for '{recipe_name}': "
            f"expected {recipe.ticks}, got {estimated}"
        )

    # Agent must not already be crafting
    if state.is_crafting(agent_id):
        active = state.get_active_craft(agent_id)
        errors.append(
            f"Agent '{agent_id}' is already crafting '{active.recipe}'"  # type: ignore[union-attr]
        )

    # If valid, update state
    if not errors:
        state.start_craft(agent_id, recipe_name, recipe.ticks)

    return errors


def _validate_craft_complete(envelope: Envelope, state: GovernorState) -> list[str]:
    """Validate craft_complete: agent must have an active craft."""
    errors: list[str] = []
    agent_id = envelope.from_agent

    if not state.is_crafting(agent_id):
        errors.append(f"Agent '{agent_id}' has no active craft to complete")
    else:
        state.complete_craft(agent_id)

    return errors


def _validate_consume(envelope: Envelope) -> list[str]:
    """Validate consume: item must exist and be consumable (energy_restore > 0)."""
    errors: list[str] = []
    item = envelope.payload.get("item", "")

    if not is_valid_item(item):
        errors.append(f"Unknown item: '{item}'")
        return errors

    cat_item = ITEMS[item]
    if cat_item.energy_restore <= 0:
        errors.append(f"Item '{item}' is not consumable (no energy_restore)")

    return errors


def _handle_join(envelope: Envelope, state: GovernorState) -> None:
    """Register the agent in state."""
    agent_id = envelope.payload.get("agent_id", envelope.from_agent)
    state.register_agent(agent_id)


def _handle_heartbeat(envelope: Envelope, state: GovernorState) -> None:
    """Record heartbeat in state."""
    state.record_heartbeat(envelope.from_agent)
