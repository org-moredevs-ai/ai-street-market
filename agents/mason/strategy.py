"""Mason strategy — pure function, no I/O.

decide_hardcoded() is kept as a test fixture. At runtime, the LLM brain is used.

Priority order each tick:
1. CONSUME soup if energy < 30 (survival)
2. GATHER stone(8) from current spawn
3. ACCEPT cheapest OFFERs for wood at <= 1.5x base_price
4. CRAFT_START wall if has stone>=4 + wood>=2 and not crafting
5. OFFER wall at 18.0 on /market/materials
6. BID for wood if no offers seen and need wood
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS, RECIPES

# Wall recipe: stone(4) + wood(2) → wall(1) in 4 ticks
WALL_RECIPE = RECIPES["wall"]

# Gather plan
GATHER_PLAN: list[tuple[str, int]] = [
    ("stone", 8),
]

# Maximum price multiplier over base_price to accept wood offers
MAX_BUY_MULTIPLIER = 1.5

# Wall selling price
WALL_SELL_PRICE = 18.0

# Bid price multiplier for wood
BID_MULTIPLIER = 1.3

# Minimum wall accept price
WALL_BASE_PRICE = 15.0

# Energy thresholds
ENERGY_CONSUME_THRESHOLD = 30.0
ENERGY_REST_THRESHOLD = 10.0

PERSONA = (
    "You are Mason Pete — you gather stone, buy wood, craft walls, sell walls.\n"
    "EVERY TICK you should:\n"
    "1. Gather stone from nature if spawn available\n"
    "2. BID for wood (quantity:2, max_price:4.5) if you have < 4 wood\n"
    "3. Accept any OFFER selling wood at price <= 4.5\n"
    "4. craft_start wall when you have 4+ stone AND 2+ wood and NOT crafting\n"
    "5. OFFER to sell wall (price: 18.0) when you have 1+ wall\n"
    "6. OFFER to sell surplus stone (price: 4.5) when you have 6+ stone\n"
    "7. Eat soup/bread when energy < 30\n"
    "IMPORTANT: You MUST bid for wood every tick until you have enough!"
)


def decide_hardcoded(state: AgentState) -> list[Action]:
    """Mason decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 0. If energy critically low, rest (only consume)
    if state.energy < ENERGY_REST_THRESHOLD:
        if budget > 0:
            for food in ("soup", "bread"):
                if state.inventory_count(food) > 0:
                    actions.append(
                        Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                    )
                    break
        return actions

    # 1. CONSUME soup/bread if energy low
    if state.energy < ENERGY_CONSUME_THRESHOLD and budget > 0:
        for food in ("soup", "bread"):
            if state.inventory_count(food) > 0:
                actions.append(
                    Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                )
                budget -= 1
                break

    # 2. GATHER stone from current spawn
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

    # 3. ACCEPT cheapest OFFERs for wood at <= 1.5x base
    wood_offers = sorted(
        [o for o in state.observed_offers if o.is_sell and o.item == "wood"],
        key=lambda o: o.price_per_unit,
    )
    for offer in wood_offers:
        if budget <= 0:
            break
        base = ITEMS["wood"].base_price
        if offer.price_per_unit <= base * MAX_BUY_MULTIPLIER:
            topic = topic_for_item(offer.item)
            actions.append(
                Action(
                    kind=ActionKind.ACCEPT,
                    params={
                        "reference_msg_id": offer.msg_id,
                        "quantity": offer.quantity,
                        "topic": topic,
                    },
                )
            )
            budget -= 1

    # 4. CRAFT_START wall if we have ingredients and not crafting
    if budget > 0 and not state.is_crafting():
        if state.has_items(WALL_RECIPE.inputs):
            actions.append(
                Action(
                    kind=ActionKind.CRAFT_START,
                    params={"recipe": "wall"},
                )
            )
            budget -= 1

    # 5. OFFER wall if we have any
    if budget > 0 and state.inventory_count("wall") > 0:
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "wall",
                    "quantity": state.inventory_count("wall"),
                    "price_per_unit": WALL_SELL_PRICE,
                },
            )
        )
        budget -= 1

    # 6. ACCEPT BIDs for wall at >= base_price
    for obs in state.observed_offers:
        if budget <= 0:
            break
        if obs.is_sell:
            continue
        if obs.item != "wall":
            continue
        if obs.price_per_unit >= WALL_BASE_PRICE:
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

    # 7. BID for wood if no offers seen and we need it
    if budget > 0 and not wood_offers:
        wood_needed = WALL_RECIPE.inputs.get("wood", 0)
        wood_have = state.inventory_count("wood")
        if wood_have < wood_needed:
            base = ITEMS["wood"].base_price
            actions.append(
                Action(
                    kind=ActionKind.BID,
                    params={
                        "item": "wood",
                        "quantity": wood_needed - wood_have,
                        "max_price_per_unit": round(base * BID_MULTIPLIER, 2),
                    },
                )
            )
            budget -= 1

    return actions
