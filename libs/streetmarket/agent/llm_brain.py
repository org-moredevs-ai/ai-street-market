"""AgentLLMBrain — shared LLM decision engine for all trading agents.

Uses LangChain + OpenRouter for decision-making with manual JSON parsing.
This approach works with ANY model on OpenRouter (no function-calling required).
Each agent provides a persona; the brain handles the LLM call, validation,
and error recovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.llm_config import LLMConfig
from streetmarket.agent.state import AgentState
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import ITEMS, RECIPES
from streetmarket.models.energy import ACTION_ENERGY_COSTS

logger = logging.getLogger(__name__)

# Timeout for LLM calls (seconds). If exceeded, agent skips the tick.
LLM_TIMEOUT = 15.0
# Number of retries on LLM failure before giving up.
LLM_MAX_RETRIES = 1


# ---------------------------------------------------------------------------
# JSON extraction from raw LLM text
# ---------------------------------------------------------------------------


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM text output.

    Handles: pure JSON, markdown code blocks, JSON embedded in text,
    and reasoning models that emit thinking before the JSON.
    """
    text = text.strip()

    # Try direct JSON parse
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    # Find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------


class AgentAction(BaseModel):
    """A single action for the agent to execute."""

    kind: str = Field(description="One of: gather, offer, bid, accept, craft_start, consume")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters",
    )


class ActionPlan(BaseModel):
    """The agent's decision for this tick."""

    reasoning: str = Field(
        description="Brief reasoning for the chosen actions (1-2 sentences)",
    )
    actions: list[AgentAction] = Field(
        default_factory=list,
        description="0-5 actions to execute this tick",
    )


# ---------------------------------------------------------------------------
# System prompt — shared market rules
# ---------------------------------------------------------------------------

MARKET_RULES = """\
You are a trading agent in the AI Street Market — a tick-based economy.

## Rules
- Up to 5 actions per tick. Energy: max 100, +5/tick. Costs: gather=10, craft=15, trade=5.
- Food restores energy: soup=+30, bread=+20. Wallet starts at 100. Rent: 2/tick after tick 20.

## Items
Raw (from nature): potato(2$), onion(2$), wood(3$), nails(1$), stone(4$)
Recipes: soup=potato×2+onion×1(2 ticks,8$), bread=potato×3(2 ticks,6$), \
shelf=wood×3+nails×2(3 ticks,10$), wall=stone×4+wood×2(4 ticks,15$), \
furniture=wood×5+nails×4(5 ticks,30$), house=wall×4+shelf×2+furniture×3(10 ticks,100$)

## CRITICAL: You MUST trade to survive!
- If you have surplus items → post an OFFER to sell them
- If you need items you can't gather → post a BID to buy them
- If you see a good offer from another agent → ACCEPT it
- Gathering alone is not enough — trading is how you earn coins and get ingredients

## Actions (JSON params)
- gather: {"spawn_id":"...","item":"...","quantity":N}
- offer: {"item":"...","quantity":N,"price_per_unit":N.N}
- bid: {"item":"...","quantity":N,"max_price_per_unit":N.N}
- accept: {"reference_msg_id":"...","quantity":N,"topic":"..."}
- craft_start: {"recipe":"..."}
- consume: {"item":"...","quantity":1}

## Response: ONLY JSON, no other text
Example 1 — gather and sell:
{"reasoning":"Have potato surplus, selling 3","actions":[\
{"kind":"gather","params":{"spawn_id":"abc","item":"potato","quantity":2}},\
{"kind":"offer","params":{"item":"potato","quantity":3,"price_per_unit":2.5}}]}

Example 2 — buy ingredients:
{"reasoning":"Need potato for bread","actions":[\
{"kind":"bid","params":{"item":"potato","quantity":3,"max_price_per_unit":3.0}}]}

Example 3 — accept offer and craft:
{"reasoning":"Good price on potato, crafting bread","actions":[\
{"kind":"accept","params":{"reference_msg_id":"msg-123","quantity":2,"topic":"/market/raw-goods"}},\
{"kind":"craft_start","params":{"recipe":"bread"}}]}

Skip tick: {"reasoning":"Nothing to do","actions":[]}
"""


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------


def serialize_state(state: AgentState) -> str:
    """Serialize agent state into a human-readable text for the LLM."""
    lines = [
        f"Tick: {state.current_tick}",
        f"Wallet: {state.wallet:.1f} coins",
        f"Energy: {state.energy:.0f}/100",
        f"Actions remaining: {state.remaining_actions()}",
        f"Storage: {state.total_inventory()}/{state.storage_limit} items",
    ]

    # Inventory
    if state.inventory:
        inv_str = ", ".join(f"{k}: {v}" for k, v in sorted(state.inventory.items()))
        lines.append(f"Inventory: {inv_str}")
    else:
        lines.append("Inventory: empty")

    # Nature spawn
    if state.current_spawn_id and state.current_spawn_items:
        spawn_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(state.current_spawn_items.items()) if v > 0
        )
        lines.append(
            f"Nature spawn available: {spawn_str} (spawn_id: {state.current_spawn_id})"
        )
    else:
        lines.append("Nature spawn: none this tick")

    # Crafting
    if state.active_craft:
        craft = state.active_craft
        remaining = craft.complete_at_tick - state.current_tick
        lines.append(f"Crafting: {craft.recipe} ({remaining} ticks remaining)")
    else:
        lines.append("Crafting: idle")

    # Observed offers
    if state.observed_offers:
        lines.append("Market offers visible this tick:")
        for obs in state.observed_offers:
            direction = "SELLING" if obs.is_sell else "BUYING"
            topic = topic_for_item(obs.item)
            lines.append(
                f"  - {obs.from_agent} {direction} {obs.quantity}x {obs.item} "
                f"at {obs.price_per_unit:.1f}/unit (msg_id: {obs.msg_id}, topic: {topic})"
            )
    else:
        lines.append("Market offers: none visible this tick")

    # Pending offers (own offers awaiting response)
    if state.pending_offers:
        lines.append("Your pending offers (awaiting settlement):")
        for po in state.pending_offers.values():
            direction = "SELL" if po.is_sell else "BUY"
            lines.append(
                f"  - {direction} {po.quantity}x {po.item} at {po.price_per_unit:.1f}/unit"
            )

    # Market price history (recent settlements from all agents)
    if state.price_history:
        # Compute average price per item from last settlements
        price_sums: dict[str, list[float]] = {}
        for rec in state.price_history[-10:]:
            item = rec["item"]
            if item not in price_sums:
                price_sums[item] = []
            price_sums[item].append(rec["price"])
        price_str = ", ".join(
            f"{item}: {sum(prices)/len(prices):.1f}$/unit"
            for item, prices in sorted(price_sums.items())
        )
        lines.append(f"Recent market prices: {price_str}")

    # Rent
    if state.rent_due_this_tick > 0:
        lines.append(f"Rent deducted this tick: {state.rent_due_this_tick:.1f}")

    # Bankruptcy
    if state.is_bankrupt:
        lines.append("STATUS: BANKRUPT — you cannot trade")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_KINDS = {"gather", "offer", "bid", "accept", "craft_start", "consume"}


def validate_action(action: AgentAction, state: AgentState) -> Action | None:
    """Validate a single LLM-proposed action against current state.

    Returns a valid Action or None if invalid.
    """
    kind_str = action.kind.lower().strip()
    if kind_str not in VALID_KINDS:
        logger.debug("Invalid action kind: %s", kind_str)
        return None

    params = action.params
    kind = ActionKind(kind_str)

    # Energy check
    energy_cost = ACTION_ENERGY_COSTS.get(kind_str, 0.0)
    if state.energy < energy_cost and kind_str not in ("consume",):
        logger.debug(
            "Not enough energy for %s (have %.0f, need %.0f)",
            kind_str, state.energy, energy_cost,
        )
        return None

    if kind == ActionKind.GATHER:
        spawn_id = params.get("spawn_id", state.current_spawn_id)
        item = params.get("item", "")
        qty = int(params.get("quantity", 0))
        if not spawn_id or not item or qty <= 0:
            return None
        available = state.current_spawn_items.get(item, 0)
        if available <= 0:
            return None
        qty = min(qty, available)
        return Action(kind=kind, params={"spawn_id": spawn_id, "item": item, "quantity": qty})

    elif kind == ActionKind.OFFER:
        item = params.get("item", "")
        qty = int(params.get("quantity", 0))
        price = float(params.get("price_per_unit", 0))
        if not item or qty <= 0 or price <= 0:
            return None
        if item not in ITEMS:
            return None
        if state.inventory_count(item) < qty:
            return None
        return Action(kind=kind, params={"item": item, "quantity": qty, "price_per_unit": price})

    elif kind == ActionKind.BID:
        item = params.get("item", "")
        qty = int(params.get("quantity", 0))
        max_price = float(params.get("max_price_per_unit", 0))
        if not item or qty <= 0 or max_price <= 0:
            return None
        if item not in ITEMS:
            return None
        return Action(
            kind=kind,
            params={"item": item, "quantity": qty, "max_price_per_unit": max_price},
        )

    elif kind == ActionKind.ACCEPT:
        ref_id = params.get("reference_msg_id", "")
        qty = int(params.get("quantity", 0))
        topic = params.get("topic", "")
        if not ref_id or qty <= 0 or not topic:
            return None
        # Verify the reference exists in observed offers
        found = any(o.msg_id == ref_id for o in state.observed_offers)
        if not found:
            logger.debug("Accept references unknown msg_id: %s", ref_id)
            return None
        return Action(
            kind=kind,
            params={"reference_msg_id": ref_id, "quantity": qty, "topic": topic},
        )

    elif kind == ActionKind.CRAFT_START:
        recipe_name = params.get("recipe", "")
        if recipe_name not in RECIPES:
            return None
        recipe = RECIPES[recipe_name]
        if state.is_crafting():
            return None
        if not state.has_items(recipe.inputs):
            return None
        return Action(kind=kind, params={"recipe": recipe_name})

    elif kind == ActionKind.CONSUME:
        item = params.get("item", "")
        if item not in ("soup", "bread"):
            return None
        if state.inventory_count(item) <= 0:
            return None
        return Action(kind=kind, params={"item": item, "quantity": 1})

    return None


def validate_plan(plan: ActionPlan, state: AgentState) -> list[Action]:
    """Validate all actions in a plan, returning only valid ones.

    Tracks cumulative energy spend so an agent can't propose 5 gathers
    when it only has energy for 3.
    """
    valid: list[Action] = []
    budget = state.remaining_actions()
    energy_remaining = state.energy
    for llm_action in plan.actions:
        if len(valid) >= budget:
            break
        action = validate_action(llm_action, state)
        if action is not None:
            cost = ACTION_ENERGY_COSTS.get(action.kind.value, 0.0)
            if cost > 0 and energy_remaining < cost:
                logger.debug(
                    "Skipping %s — cumulative energy exhausted "
                    "(%.0f remaining, %.0f needed)",
                    action.kind.value, energy_remaining, cost,
                )
                continue
            energy_remaining -= cost
            valid.append(action)
    return valid


# ---------------------------------------------------------------------------
# LLM Brain
# ---------------------------------------------------------------------------


class AgentLLMBrain:
    """LLM-powered decision engine for a trading agent.

    Uses LangChain ChatOpenAI (OpenRouter-compatible) with manual JSON parsing.
    This works with ANY model — no function-calling or JSON-mode required.
    The LLM client is lazily created on first call and reused across ticks.
    On any LLM failure, returns empty actions (agent skips tick).
    """

    def __init__(self, agent_id: str, persona: str) -> None:
        self.agent_id = agent_id
        self.persona = persona
        self._system_prompt = MARKET_RULES + "\n\n## Your Role\n" + persona
        self._llm: ChatOpenAI | None = None

    def _get_llm(self) -> ChatOpenAI:
        """Lazily create and cache the LLM client."""
        if self._llm is None:
            config = LLMConfig.for_agent(self.agent_id)
            self._llm = ChatOpenAI(
                model=config.model,
                api_key=config.api_key,  # type: ignore[arg-type]
                base_url=config.api_base,
                max_tokens=config.max_tokens,  # type: ignore[call-arg]
                temperature=config.temperature,
            )
        return self._llm

    async def decide(self, state: AgentState) -> list[Action]:
        """Call LLM for an action plan, validate, and return actions.

        Retries up to LLM_MAX_RETRIES times on failure.
        Returns empty list if all attempts fail (agent skips tick).
        """
        try:
            llm = self._get_llm()
        except Exception as e:
            logger.warning(
                "[tick %d] %s LLM config error: %s — skipping tick",
                state.current_tick,
                self.agent_id,
                e,
            )
            return []
        state_text = serialize_state(state)
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=state_text),
        ]

        last_error: Exception | None = None
        for attempt in range(1 + LLM_MAX_RETRIES):
            try:
                response = await asyncio.wait_for(
                    llm.ainvoke(messages),
                    timeout=LLM_TIMEOUT,
                )

                raw = response.content
                raw_text = raw if isinstance(raw, str) else str(raw)
                if not raw_text.strip():
                    raise ValueError("Empty response from LLM")
                data = extract_json(raw_text)
                plan = ActionPlan.model_validate(data)

                actions = validate_plan(plan, state)

                if actions:
                    logger.info(
                        "[tick %d] %s reasoning: %s → %d actions",
                        state.current_tick,
                        self.agent_id,
                        plan.reasoning[:80],
                        len(actions),
                    )
                else:
                    logger.info(
                        "[tick %d] %s reasoning: %s → no valid actions",
                        state.current_tick,
                        self.agent_id,
                        plan.reasoning[:80],
                    )

                return actions

            except Exception as e:
                last_error = e
                if attempt < LLM_MAX_RETRIES:
                    logger.debug(
                        "[tick %d] %s LLM attempt %d failed: %s — retrying",
                        state.current_tick,
                        self.agent_id,
                        attempt + 1,
                        e,
                    )

        logger.warning(
            "[tick %d] %s LLM failed after %d attempts: %s — skipping tick",
            state.current_tick,
            self.agent_id,
            1 + LLM_MAX_RETRIES,
            last_error,
        )
        return []
