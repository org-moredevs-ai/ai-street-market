"""Builder strategy — pure function, no I/O.

decide_hardcoded() is kept as a test fixture. At runtime, the LLM brain is used.

Priority order each tick:
1. CONSUME bread/soup if energy < 30 (survival)
2. ACCEPT cheapest OFFERs for wall, shelf, furniture at <= 1.5x base_price
3. CRAFT_START house if has wall>=4 + shelf>=2 + furniture>=3 and not crafting
4. OFFER house at 120.0 on /market/housing
5. BID for missing materials if no offers seen
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS, RECIPES

# House recipe: wall(4) + shelf(2) + furniture(3) → house(1) in 10 ticks
HOUSE_RECIPE = RECIPES["house"]
INGREDIENTS = list(HOUSE_RECIPE.inputs.keys())  # ["wall", "shelf", "furniture"]

# Maximum price multiplier over base_price to accept
MAX_BUY_MULTIPLIER = 1.5

# House selling price
HOUSE_SELL_PRICE = 120.0

# Bid price multiplier
BID_MULTIPLIER = 1.3

# Energy thresholds
ENERGY_CONSUME_THRESHOLD = 30.0
ENERGY_REST_THRESHOLD = 10.0

PERSONA = (
    "You are Builder Bob — ambitious, visionary, and the biggest spender in the market.\n"
    "You buy walls, shelves, and furniture to craft houses.\n"
    "Strategy tips:\n"
    "- Buy building materials (wall, shelf, furniture) at reasonable prices\n"
    "- Craft house when you have 4 wall + 2 shelf + 3 furniture (takes 10 ticks!)\n"
    "- Sell houses at ~120 coins — they're the most valuable item\n"
    "- Bid for missing materials if no offers visible\n"
    "- Eat bread or soup when energy drops below 30\n"
    "- Be patient — house crafting is a long investment"
)


def decide_hardcoded(state: AgentState) -> list[Action]:
    """Builder decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 0. If energy critically low, rest (only consume)
    if state.energy < ENERGY_REST_THRESHOLD:
        if budget > 0:
            for food in ("bread", "soup"):
                if state.inventory_count(food) > 0:
                    actions.append(
                        Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                    )
                    break
        return actions

    # 1. CONSUME bread/soup if energy low
    if state.energy < ENERGY_CONSUME_THRESHOLD and budget > 0:
        for food in ("bread", "soup"):
            if state.inventory_count(food) > 0:
                actions.append(
                    Action(kind=ActionKind.CONSUME, params={"item": food, "quantity": 1})
                )
                budget -= 1
                break

    # 2. ACCEPT cheapest OFFERs for wall, shelf, furniture at <= 1.5x base
    material_offers = sorted(
        [o for o in state.observed_offers if o.is_sell and o.item in INGREDIENTS],
        key=lambda o: o.price_per_unit,
    )
    for offer in material_offers:
        if budget <= 0:
            break
        base = ITEMS[offer.item].base_price
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

    # 3. CRAFT_START house if we have ingredients and not crafting
    if budget > 0 and not state.is_crafting():
        if state.has_items(HOUSE_RECIPE.inputs):
            actions.append(
                Action(
                    kind=ActionKind.CRAFT_START,
                    params={"recipe": "house"},
                )
            )
            budget -= 1

    # 4. OFFER house if we have any
    if budget > 0 and state.inventory_count("house") > 0:
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "house",
                    "quantity": state.inventory_count("house"),
                    "price_per_unit": HOUSE_SELL_PRICE,
                },
            )
        )
        budget -= 1

    # 5. BID for missing materials if no offers seen
    if budget > 0 and not material_offers:
        for ingredient in INGREDIENTS:
            if budget <= 0:
                break
            needed = HOUSE_RECIPE.inputs[ingredient]
            have = state.inventory_count(ingredient)
            if have < needed:
                base = ITEMS[ingredient].base_price
                actions.append(
                    Action(
                        kind=ActionKind.BID,
                        params={
                            "item": ingredient,
                            "quantity": needed - have,
                            "max_price_per_unit": round(base * BID_MULTIPLIER, 2),
                        },
                    )
                )
                budget -= 1

    return actions
