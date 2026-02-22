"""Farmer strategy — pure function, no I/O.

Priority order each tick:
1. GATHER potato(10) + onion(8) from current spawn
2. ACCEPT any BIDs for potato/onion at >= base_price
3. OFFER surplus potato/onion at 1.2x base_price
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS

# Farmer gathers these items and quantities each tick
GATHER_PLAN: list[tuple[str, int]] = [
    ("potato", 10),
    ("onion", 8),
]

# Minimum inventory to keep before selling
KEEP_RESERVE = 2

# Sell price multiplier over base_price
SELL_MULTIPLIER = 1.2

# Minimum acceptable price (fraction of base_price)
MIN_ACCEPT_FRACTION = 1.0


def decide(state: AgentState) -> list[Action]:
    """Farmer decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 1. GATHER from current spawn
    if state.current_spawn_id:
        for item, qty in GATHER_PLAN:
            if budget <= 0:
                break
            available = state.current_spawn_items.get(item, 0)
            if available > 0:
                gather_qty = min(qty, available)
                actions.append(
                    Action(
                        kind=ActionKind.GATHER,
                        params={
                            "spawn_id": state.current_spawn_id,
                            "item": item,
                            "quantity": gather_qty,
                        },
                    )
                )
                budget -= 1

    # 2. ACCEPT BIDs for potato/onion at >= base_price
    for obs in state.observed_offers:
        if budget <= 0:
            break
        if obs.is_sell:
            continue  # We only accept BIDs (buy orders from others)
        if obs.item not in ("potato", "onion"):
            continue
        base = ITEMS[obs.item].base_price
        if obs.price_per_unit >= base * MIN_ACCEPT_FRACTION:
            topic = topic_for_item(obs.item)
            actions.append(
                Action(
                    kind=ActionKind.ACCEPT,
                    params={
                        "reference_msg_id": obs.msg_id,
                        "quantity": obs.quantity,
                        "topic": topic,
                    },
                )
            )
            budget -= 1

    # 3. OFFER surplus potato/onion
    for item, _ in GATHER_PLAN:
        if budget <= 0:
            break
        count = state.inventory_count(item)
        surplus = count - KEEP_RESERVE
        if surplus > 0:
            base = ITEMS[item].base_price
            actions.append(
                Action(
                    kind=ActionKind.OFFER,
                    params={
                        "item": item,
                        "quantity": surplus,
                        "price_per_unit": round(base * SELL_MULTIPLIER, 2),
                    },
                )
            )
            budget -= 1

    return actions
