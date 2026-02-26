"""Strategy — the brain of your agent.

Implement decide(state) to return a list of actions.
This template gathers potatoes and sells surplus at a profit.
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState


async def decide(state: AgentState) -> list[Action]:
    """Decide what to do this tick based on current state."""
    actions: list[Action] = []

    # 1. Gather potatoes if a spawn is available
    if state.current_spawn_id and state.energy >= 10:
        available = state.current_spawn_items.get("potato", 0)
        if available > 0:
            qty = min(available, 3)
            actions.append(
                Action(
                    kind=ActionKind.GATHER,
                    params={
                        "spawn_id": state.current_spawn_id,
                        "item": "potato",
                        "quantity": qty,
                    },
                )
            )

    # 2. Sell surplus potatoes (keep 5 in reserve)
    potatoes = state.inventory_count("potato")
    if potatoes > 5:
        sell_qty = potatoes - 5
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "potato",
                    "quantity": sell_qty,
                    "price_per_unit": 2.5,
                },
            )
        )

    # 3. Accept bids for potatoes at a good price
    for offer in state.observed_offers:
        if not offer.is_sell and offer.item == "potato" and offer.price_per_unit >= 2.0:
            accept_qty = min(offer.quantity, state.inventory_count("potato") - 5)
            if accept_qty > 0:
                actions.append(
                    Action(
                        kind=ActionKind.ACCEPT,
                        params={
                            "reference_msg_id": offer.msg_id,
                            "quantity": accept_qty,
                            "topic": "/market/raw-goods",
                        },
                    )
                )
                break  # One accept per tick

    return actions
