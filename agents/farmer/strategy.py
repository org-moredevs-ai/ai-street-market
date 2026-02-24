"""Farmer strategy — pure function, no I/O.

decide_hardcoded() is kept as a test fixture. At runtime, the LLM brain is used.

Priority order each tick:
1. CONSUME soup if energy < 30
2. GATHER potato(10) + onion(8) from current spawn
3. ACCEPT any BIDs for potato/onion at >= base_price
4. OFFER surplus potato/onion at 1.2x base_price
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

# Energy thresholds
ENERGY_CONSUME_THRESHOLD = 30.0
ENERGY_REST_THRESHOLD = 10.0

PERSONA = (
    "You are Farmer Joe — a practical, reliable farmer who's a bit grumpy about prices.\n"
    "You gather potato and onion from nature, then sell surplus on the raw-goods market.\n"
    "Strategy tips:\n"
    "- Always gather when spawn is available (potato first, then onion)\n"
    "- Keep a small reserve (2 of each) before selling\n"
    "- Sell at ~1.2x base price — don't be greedy, steady income matters\n"
    "- Accept buy bids at or above base price\n"
    "- Eat soup or bread when energy drops below 30\n"
    "- If energy is critically low (<10), only consume food and rest"
)


def decide_hardcoded(state: AgentState) -> list[Action]:
    """Farmer decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 0. If energy is critically low, rest (do nothing except consume)
    if state.energy < ENERGY_REST_THRESHOLD:
        if budget > 0:
            for food in ("soup", "bread"):
                if state.inventory_count(food) > 0:
                    actions.append(
                        Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                    )
                    break
        return actions

    # 1. CONSUME soup/bread if energy is low
    if state.energy < ENERGY_CONSUME_THRESHOLD and budget > 0:
        for food in ("soup", "bread"):
            if state.inventory_count(food) > 0:
                actions.append(
                    Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                )
                budget -= 1
                break

    # 2. GATHER from current spawn
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

    # 3. ACCEPT BIDs for potato/onion at >= base_price
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

    # 4. OFFER surplus potato/onion
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
