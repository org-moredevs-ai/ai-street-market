"""Baker strategy — pure function, no I/O.

decide_hardcoded() is kept as a test fixture. At runtime, the LLM brain is used.

Priority order each tick:
1. CONSUME bread/soup if energy < 30 (eat own product first)
2. ACCEPT cheapest OFFERs for potato at <= 1.5x base_price
3. CRAFT_START bread if has potato>=3 and not crafting
4. OFFER bread at 8.0 on /market/food
5. BID for potato if no offers seen
"""

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS, RECIPES

# Bread recipe: potato(3) → bread(1) in 2 ticks
BREAD_RECIPE = RECIPES["bread"]

# Maximum price multiplier over base_price to accept
MAX_BUY_MULTIPLIER = 1.5

# Bread selling price
BREAD_SELL_PRICE = 8.0

# Bid price multiplier for potato
BID_MULTIPLIER = 1.3

# Energy thresholds
ENERGY_CONSUME_THRESHOLD = 30.0
ENERGY_REST_THRESHOLD = 10.0

PERSONA = (
    "You are Baker Bella — you buy potato, craft bread, sell bread.\n"
    "EVERY TICK you should:\n"
    "1. BID for potato (quantity:3, max_price:3.0) if you have < 6 potato\n"
    "2. Accept any OFFER selling potato at price <= 3.0\n"
    "3. craft_start bread when you have 3+ potato and NOT crafting\n"
    "4. OFFER to sell bread (price: 8.0) when you have 2+ bread\n"
    "5. Eat bread when energy < 30\n"
    "IMPORTANT: You MUST bid for potato every tick until you have 6+!"
)


def decide_hardcoded(state: AgentState) -> list[Action]:
    """Baker decision logic — returns actions to execute this tick."""
    actions: list[Action] = []
    budget = state.remaining_actions()

    # 0. If energy critically low, rest (only consume)
    if state.energy < ENERGY_REST_THRESHOLD:
        if budget > 0:
            # Prefer bread, then soup
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

    # 2. ACCEPT cheapest OFFERs for potato at <= 1.5x base
    potato_offers = sorted(
        [o for o in state.observed_offers if o.is_sell and o.item == "potato"],
        key=lambda o: o.price_per_unit,
    )
    for offer in potato_offers:
        if budget <= 0:
            break
        base = ITEMS["potato"].base_price
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

    # 3. CRAFT_START bread if we have ingredients and not crafting
    if budget > 0 and not state.is_crafting():
        if state.has_items(BREAD_RECIPE.inputs):
            actions.append(
                Action(
                    kind=ActionKind.CRAFT_START,
                    params={"recipe": "bread"},
                )
            )
            budget -= 1

    # 4. OFFER bread if we have any (keep 1 for emergency consuming)
    bread_count = state.inventory_count("bread")
    bread_to_sell = bread_count - 1 if bread_count > 1 else 0
    if budget > 0 and bread_to_sell > 0:
        actions.append(
            Action(
                kind=ActionKind.OFFER,
                params={
                    "item": "bread",
                    "quantity": bread_to_sell,
                    "price_per_unit": BREAD_SELL_PRICE,
                },
            )
        )
        budget -= 1

    # 5. BID for potato if no offers seen and we need it
    if budget > 0 and not potato_offers:
        potato_needed = BREAD_RECIPE.inputs.get("potato", 0)
        potato_have = state.inventory_count("potato")
        if potato_have < potato_needed:
            base = ITEMS["potato"].base_price
            actions.append(
                Action(
                    kind=ActionKind.BID,
                    params={
                        "item": "potato",
                        "quantity": potato_needed - potato_have,
                        "max_price_per_unit": round(base * BID_MULTIPLIER, 2),
                    },
                )
            )
            budget -= 1

    return actions
