"""Chef strategy — pure function, no I/O.

decide_hardcoded() is kept as a test fixture. At runtime, the LLM brain is used.

Priority order each tick:
1. CONSUME soup if energy < 30 (eat own product)
2. ACCEPT cheapest OFFERs for potato/onion at <= 1.5x base_price
3. CRAFT_START soup if has potato>=2 + onion>=1 and not crafting
4. OFFER soup at 10.0 on /market/food
5. BID for missing ingredients if no offers seen
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS, RECIPES

# Ingredients needed for soup
SOUP_RECIPE = RECIPES["soup"]
INGREDIENTS = list(SOUP_RECIPE.inputs.keys())  # ["potato", "onion"]

# Maximum price multiplier over base_price to accept
MAX_BUY_MULTIPLIER = 1.5

# Soup selling price
SOUP_SELL_PRICE = 10.0

# Bid price multiplier (what we offer to pay)
BID_MULTIPLIER = 1.3

# Energy thresholds
ENERGY_CONSUME_THRESHOLD = 30.0
ENERGY_REST_THRESHOLD = 10.0

PERSONA = (
    "You are Chef Clara — you buy potato+onion, craft soup, sell soup.\n"
    "EVERY TICK you should:\n"
    "1. BID for potato (quantity:2, max_price:3.0) if you have < 4 potato\n"
    "2. BID for onion (quantity:1, max_price:3.0) if you have < 2 onion\n"
    "3. Accept any OFFER selling potato or onion at price <= 3.0\n"
    "4. craft_start soup when you have 2+ potato AND 1+ onion and NOT crafting\n"
    "5. OFFER to sell soup (price: 10.0) when you have 2+ soup\n"
    "6. Eat soup when energy < 30\n"
    "IMPORTANT: You MUST bid for ingredients every tick until you have enough!"
)


def decide_hardcoded(state: AgentState) -> list[Action]:
    """Chef decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 0. If energy is critically low, rest (only consume)
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

    # 2. ACCEPT cheapest OFFERs for potato/onion at <= 1.5x base
    sell_offers = sorted(
        [o for o in state.observed_offers if o.is_sell and o.item in INGREDIENTS],
        key=lambda o: o.price_per_unit,
    )
    for offer in sell_offers:
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

    # 3. CRAFT_START soup if we have ingredients and not crafting
    if budget > 0 and not state.is_crafting():
        if state.has_items(SOUP_RECIPE.inputs):
            actions.append(
                Action(
                    kind=ActionKind.CRAFT_START,
                    params={"recipe": "soup"},
                )
            )
            budget -= 1

    # 4. OFFER soup if we have any (keep 1 for emergency consuming)
    soup_count = state.inventory_count("soup")
    soup_to_sell = soup_count - 1 if soup_count > 1 else 0
    if budget > 0 and soup_to_sell > 0:
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "soup",
                    "quantity": soup_to_sell,
                    "price_per_unit": SOUP_SELL_PRICE,
                },
            )
        )
        budget -= 1

    # 5. BID for missing ingredients if no offers seen
    if budget > 0 and not sell_offers:
        for ingredient in INGREDIENTS:
            if budget <= 0:
                break
            needed = SOUP_RECIPE.inputs[ingredient]
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
