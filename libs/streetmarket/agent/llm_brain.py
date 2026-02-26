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
# Set to 0 for free-tier models (tight rate limits); increase for paid models.
LLM_MAX_RETRIES = 0


# ---------------------------------------------------------------------------
# JSON extraction from raw LLM text
# ---------------------------------------------------------------------------


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM text output.

    Handles: pure JSON, markdown code blocks, JSON embedded in text,
    and reasoning models that emit thinking before the JSON.
    """
    # Strip <think>...</think> tags from reasoning models (e.g. Qwen, DeepSeek)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
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

    thoughts: str = Field(
        default="",
        description="Your inner monologue — what you're thinking/feeling (2-3 sentences, in character)",
    )
    speech: str = Field(
        default="",
        description="What you say out loud to the market (1 sentence, natural dialogue)",
    )
    mood: str = Field(
        default="calm",
        description="Your current mood (one word: happy, frustrated, worried, excited, calm, desperate, hopeful, angry, content, bored)",
    )
    actions: list[AgentAction] = Field(
        default_factory=list,
        description="0-5 actions to execute this tick",
    )

    # Backward compat: if old models return "reasoning", map it to thoughts
    reasoning: str = Field(default="", exclude=True)


# ---------------------------------------------------------------------------
# System prompt — shared market rules
# ---------------------------------------------------------------------------

MARKET_RULES = """\
You are a character in the AI Street Market — a living economy where you trade to survive.
Stay in character. Think and speak like a real person with feelings and opinions.

## Economy Rules
- Up to 5 actions per tick. Energy: max 100, regen +5/tick. Costs: gather=10, craft=15, trade=5.
- Food restores energy: soup=+30, bread=+20. Wallet starts at 100. Rent: 0.5/tick after tick 50.
- Perishable items rot! potato=100t, onion=80t, soup=150t, bread=180t. Sell before they spoil!
- If you can't pay rent, the market seizes your cheapest items at 70% of market price.

## Items
Raw: potato(2$), onion(2$), wood(3$), nails(1$), stone(4$)
Recipes: soup=potato×2+onion×1(2t,8$), bread=potato×3(2t,6$), \
shelf=wood×3+nails×2(3t,10$), wall=stone×4+wood×2(4t,15$), \
furniture=wood×5+nails×4(5t,30$), house=wall×4+shelf×2+furniture×3(10t,100$)

## Survival: You MUST trade!
- Surplus items → OFFER to sell them (call out your prices!)
- Need items you can't gather → BID to buy them
- See a good offer → ACCEPT it
- Gathering alone won't pay the rent

## Actions
- gather: {"spawn_id":"...","item":"...","quantity":N}
- offer: {"item":"...","quantity":N,"price_per_unit":N.N}
- bid: {"item":"...","quantity":N,"max_price_per_unit":N.N}
- accept: {"reference_msg_id":"...","quantity":N,"topic":"..."}
- craft_start: {"recipe":"..."}
- consume: {"item":"...","quantity":1}

## Response format: ONLY valid JSON
{
  "thoughts": "Your inner monologue (2-3 sentences, in character, with personality and emotion)",
  "speech": "What you say out loud to the market (natural dialogue, 1 sentence)",
  "mood": "one word: happy/frustrated/worried/excited/calm/desperate/hopeful/angry/content/bored",
  "actions": [{"kind":"...","params":{...}}, ...]
}

Example:
{"thoughts":"The field is full of potatoes today, beautiful! But nobody's buying... my wallet is getting thin. Gotta keep offering, someone will come.","speech":"Fresh potatoes, straight from the ground! Two-fifty each, best price in town!","mood":"hopeful","actions":[{"kind":"gather","params":{"spawn_id":"abc","item":"potato","quantity":5}},{"kind":"offer","params":{"item":"potato","quantity":10,"price_per_unit":2.5}}]}

Skip tick:
{"thoughts":"Nothing to do right now, just watching the clouds...","speech":"*whistles*","mood":"bored","actions":[]}
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

    # Spoilage alerts
    if state.spoiled_this_tick:
        spoil_str = ", ".join(
            f"{s['quantity']}x {s['item']}" for s in state.spoiled_this_tick
        )
        lines.append(f"SPOILAGE ALERT: {spoil_str} rotted in your inventory!")

    # Confiscation alerts
    if state.confiscated_this_tick:
        conf_str = ", ".join(
            f"{qty}x {item}" for item, qty in state.confiscated_this_tick.items()
        )
        lines.append(f"CONFISCATION: Market seized {conf_str} for unpaid rent!")

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
        # BF-1: Storage check — don't gather more than storage allows
        remaining_storage = state.storage_limit - state.total_inventory()
        if remaining_storage <= 0:
            return None
        qty = min(qty, remaining_storage)
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
        self._system_prompt = MARKET_RULES + "\n\n## Your Character\n" + persona
        self._llm: ChatOpenAI | None = None
        self._last_status: dict | None = None

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

                # Use thoughts if present, fall back to reasoning for old models
                thoughts = plan.thoughts or plan.reasoning or ""
                speech = plan.speech or ""
                # Strip non-alpha chars (LLMs sometimes return "-content" etc.)
                mood = re.sub(r"[^a-z]", "", (plan.mood or "calm").lower()) or "calm"

                if actions:
                    logger.info(
                        "[tick %d] %s [%s] %s → %d actions",
                        state.current_tick,
                        self.agent_id,
                        mood,
                        thoughts[:80],
                        len(actions),
                    )
                else:
                    logger.info(
                        "[tick %d] %s [%s] %s → no valid actions",
                        state.current_tick,
                        self.agent_id,
                        mood,
                        thoughts[:80],
                    )
                if speech:
                    logger.info(
                        "[tick %d] %s says: \"%s\"",
                        state.current_tick,
                        self.agent_id,
                        speech[:100],
                    )

                # Store status for the agent base to publish
                self._last_status = {
                    "thoughts": thoughts[:300],
                    "speech": speech[:200],
                    "mood": mood[:20],
                    "action_count": len(actions),
                }

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
