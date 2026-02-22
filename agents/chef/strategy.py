"""Chef strategy — pure function, no I/O.

Priority order each tick:
1. ACCEPT cheapest OFFERs for potato/onion at <= 1.5x base_price
2. CRAFT_START soup if has potato>=2 + onion>=1 and not crafting
3. OFFER soup at 10.0 on /market/food
4. BID for missing ingredients if no offers seen
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


def decide(state: AgentState) -> list[Action]:
    """Chef decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 1. ACCEPT cheapest OFFERs for potato/onion at <= 1.5x base
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

    # 2. CRAFT_START soup if we have ingredients and not crafting
    if budget > 0 and not state.is_crafting():
        if state.has_items(SOUP_RECIPE.inputs):
            actions.append(
                Action(
                    kind=ActionKind.CRAFT_START,
                    params={"recipe": "soup"},
                )
            )
            budget -= 1

    # 3. OFFER soup if we have any
    if budget > 0 and state.inventory_count("soup") > 0:
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "soup",
                    "quantity": state.inventory_count("soup"),
                    "price_per_unit": SOUP_SELL_PRICE,
                },
            )
        )
        budget -= 1

    # 4. BID for missing ingredients if no offers seen
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
