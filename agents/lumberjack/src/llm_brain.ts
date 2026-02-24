/**
 * LLM Brain for the Lumberjack agent — uses OpenRouter via OpenAI-compatible API.
 *
 * Mirrors the Python AgentLLMBrain pattern. On any LLM failure, returns
 * empty actions (agent skips tick).
 */

import { ChatOpenAI } from "@langchain/openai";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import {
  type AgentState,
  inventoryCount,
  remainingActions,
} from "./state.js";
import { topicForItem } from "./protocol.js";
import type { Action } from "./strategy.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface LLMConfig {
  apiKey: string;
  apiBase: string;
  model: string;
  maxTokens: number;
  temperature: number;
}

export function loadConfig(): LLMConfig {
  const prefix = "LUMBERJACK";
  return {
    apiKey: process.env.OPENROUTER_API_KEY ?? "",
    apiBase:
      process.env.OPENROUTER_API_BASE ?? "https://openrouter.ai/api/v1",
    model:
      process.env[`${prefix}_MODEL`] ??
      process.env.DEFAULT_MODEL ??
      "",
    maxTokens: parseInt(
      process.env[`${prefix}_MAX_TOKENS`] ??
        process.env.DEFAULT_MAX_TOKENS ??
        "400",
      10
    ),
    temperature: parseFloat(
      process.env[`${prefix}_TEMPERATURE`] ??
        process.env.DEFAULT_TEMPERATURE ??
        "0.7"
    ),
  };
}

// ---------------------------------------------------------------------------
// Structured output schema
// ---------------------------------------------------------------------------

const AgentActionSchema = z.object({
  kind: z.string().describe("One of: gather, offer, bid, accept, craft_start, consume"),
  params: z.record(z.unknown()).describe("Action-specific parameters"),
});

const ActionPlanSchema = z.object({
  reasoning: z.string().describe("Brief reasoning (1-2 sentences)"),
  actions: z.array(AgentActionSchema).describe("0-5 actions to execute"),
});

type ActionPlan = z.infer<typeof ActionPlanSchema>;
type AgentActionLLM = z.infer<typeof AgentActionSchema>;

// ---------------------------------------------------------------------------
// Market rules prompt
// ---------------------------------------------------------------------------

const MARKET_RULES = `You are a trading agent in the AI Street Market — a tick-based economy simulation.

## Economy Rules
- Each tick you may take up to 5 actions.
- Energy: max 100, regenerates 5/tick. Costs: gather=10, craft_start=15, offer/bid/accept=5.
- Food restores energy: soup=+30, bread=+20.
- Wallet starts at 100 coins. Rent: 2 coins/tick after tick 20 (house exempts).

## Items & Prices
Raw materials: potato(2.0), onion(2.0), wood(3.0), nails(1.0), stone(4.0)
Craftable: soup(8.0), bread(6.0), shelf(10.0), wall(15.0), furniture(30.0), house(100.0)
Recipes: shelf = wood(3) + nails(2) in 3 ticks

## Action Parameter Schemas
- gather: {"spawn_id": str, "item": str, "quantity": int}
- offer: {"item": str, "quantity": int, "price_per_unit": float}
- bid: {"item": str, "quantity": int, "max_price_per_unit": float}
- accept: {"reference_msg_id": str, "quantity": int, "topic": str}
- craft_start: {"recipe": str}
- consume: {"item": str, "quantity": 1}`;

export const LUMBERJACK_PERSONA = `You are Jack Lumber — strong, quiet, and proud of your craftsmanship.
You gather wood and nails from nature, then craft shelves to sell on the materials market.
Strategy tips:
- Always gather when spawn is available (wood first, then nails)
- Craft shelf whenever you have 3 wood + 2 nails and aren't crafting
- Sell shelves at ~12 coins
- Accept buy bids for shelf at >= 10 coins (base price)
- Bid for soup/bread if you have no food and energy is getting low
- Eat soup or bread when energy drops below 30`;

// ---------------------------------------------------------------------------
// State serialization
// ---------------------------------------------------------------------------

export function serializeState(state: AgentState): string {
  const lines: string[] = [
    `Tick: ${state.currentTick}`,
    `Wallet: ${state.wallet.toFixed(1)} coins`,
    `Energy: ${Math.floor(state.energy)}/100`,
    `Actions remaining: ${remainingActions(state)}`,
  ];

  const inv = Object.entries(state.inventory);
  if (inv.length > 0) {
    lines.push(
      "Inventory: " + inv.map(([k, v]) => `${k}: ${v}`).join(", ")
    );
  } else {
    lines.push("Inventory: empty");
  }

  if (state.currentSpawnId) {
    const items = Object.entries(state.currentSpawnItems)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => `${k}: ${v}`)
      .join(", ");
    lines.push(
      `Nature spawn available: ${items} (spawn_id: ${state.currentSpawnId})`
    );
  } else {
    lines.push("Nature spawn: none this tick");
  }

  if (state.activeCraft) {
    const remaining =
      state.activeCraft.startedTick +
      state.activeCraft.durationTicks -
      state.currentTick;
    lines.push(
      `Crafting: ${state.activeCraft.recipe} (${remaining} ticks remaining)`
    );
  } else {
    lines.push("Crafting: idle");
  }

  if (state.observedOffers.length > 0) {
    lines.push("Market offers visible this tick:");
    for (const obs of state.observedOffers) {
      const direction = obs.isSell ? "SELLING" : "BUYING";
      const topic = topicForItem(obs.item);
      lines.push(
        `  - ${obs.fromAgent} ${direction} ${obs.quantity}x ${obs.item} at ${obs.pricePerUnit.toFixed(1)}/unit (msg_id: ${obs.msgId}, topic: ${topic})`
      );
    }
  } else {
    lines.push("Market offers: none visible this tick");
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const VALID_KINDS = new Set([
  "gather",
  "offer",
  "bid",
  "accept",
  "craft_start",
  "consume",
]);

const VALID_ITEMS = new Set([
  "potato",
  "onion",
  "wood",
  "nails",
  "stone",
  "soup",
  "bread",
  "shelf",
  "wall",
  "furniture",
  "house",
]);

const SHELF_INPUTS: Record<string, number> = { wood: 3, nails: 2 };

const ENERGY_COSTS: Record<string, number> = {
  gather: 10,
  craft_start: 15,
  offer: 5,
  bid: 5,
  accept: 5,
};

export function validateAction(
  llmAction: AgentActionLLM,
  state: AgentState
): Action | null {
  const kind = llmAction.kind.toLowerCase().trim();
  if (!VALID_KINDS.has(kind)) return null;

  const params = llmAction.params as Record<string, unknown>;

  // Energy check
  const cost = ENERGY_COSTS[kind] ?? 0;
  if (state.energy < cost && kind !== "consume") return null;

  switch (kind) {
    case "gather": {
      const spawnId =
        (params.spawn_id as string) ?? state.currentSpawnId;
      const item = params.item as string;
      const qty = Number(params.quantity ?? 0);
      if (!spawnId || !item || qty <= 0) return null;
      const available = state.currentSpawnItems[item] ?? 0;
      if (available <= 0) return null;
      return {
        kind: "gather",
        params: {
          spawn_id: spawnId,
          item,
          quantity: Math.min(qty, available),
        },
      };
    }

    case "offer": {
      const item = params.item as string;
      const qty = Number(params.quantity ?? 0);
      const price = Number(params.price_per_unit ?? 0);
      if (!item || qty <= 0 || price <= 0) return null;
      if (!VALID_ITEMS.has(item)) return null;
      if (inventoryCount(state, item) < qty) return null;
      return { kind: "offer", params: { item, quantity: qty, price_per_unit: price } };
    }

    case "bid": {
      const item = params.item as string;
      const qty = Number(params.quantity ?? 0);
      const maxPrice = Number(params.max_price_per_unit ?? 0);
      if (!item || qty <= 0 || maxPrice <= 0) return null;
      if (!VALID_ITEMS.has(item)) return null;
      return {
        kind: "bid",
        params: { item, quantity: qty, max_price_per_unit: maxPrice },
      };
    }

    case "accept": {
      const refId = params.reference_msg_id as string;
      const qty = Number(params.quantity ?? 0);
      const topic = params.topic as string;
      if (!refId || qty <= 0 || !topic) return null;
      const found = state.observedOffers.some((o) => o.msgId === refId);
      if (!found) return null;
      return {
        kind: "accept",
        params: { reference_msg_id: refId, quantity: qty, topic },
      };
    }

    case "craft_start": {
      const recipe = params.recipe as string;
      if (recipe !== "shelf") return null; // Lumberjack only crafts shelf
      if (state.activeCraft) return null;
      const hasAll = Object.entries(SHELF_INPUTS).every(
        ([item, qty]) => inventoryCount(state, item) >= qty
      );
      if (!hasAll) return null;
      return { kind: "craft_start", params: { recipe } };
    }

    case "consume": {
      const item = params.item as string;
      if (item !== "soup" && item !== "bread") return null;
      if (inventoryCount(state, item) <= 0) return null;
      return { kind: "consume", params: { item, quantity: 1 } };
    }

    default:
      return null;
  }
}

export function validatePlan(
  plan: ActionPlan,
  state: AgentState
): Action[] {
  const valid: Action[] = [];
  const budget = remainingActions(state);
  for (const llmAction of plan.actions) {
    if (valid.length >= budget) break;
    const action = validateAction(llmAction, state);
    if (action) valid.push(action);
  }
  return valid;
}

// ---------------------------------------------------------------------------
// LLM Brain
// ---------------------------------------------------------------------------

export class LumberjackLLMBrain {
  private systemPrompt: string;

  constructor() {
    this.systemPrompt =
      MARKET_RULES + "\n\n## Your Role\n" + LUMBERJACK_PERSONA;
  }

  async decide(state: AgentState): Promise<Action[]> {
    try {
      const config = loadConfig();
      if (!config.apiKey) {
        console.warn(
          `[tick ${state.currentTick}] lumberjack-01: no API key — skipping tick`
        );
        return [];
      }

      const llm = new ChatOpenAI({
        model: config.model,
        apiKey: config.apiKey,
        configuration: { baseURL: config.apiBase },
        maxTokens: config.maxTokens,
        temperature: config.temperature,
      });

      const structured = llm.withStructuredOutput(ActionPlanSchema);
      const stateText = serializeState(state);

      const plan = await structured.invoke([
        new SystemMessage(this.systemPrompt),
        new HumanMessage(stateText),
      ]);

      const actions = validatePlan(plan, state);

      if (actions.length > 0) {
        console.log(
          `[tick ${state.currentTick}] lumberjack-01 reasoning: ${plan.reasoning.slice(0, 80)} → ${actions.length} actions`
        );
      }

      return actions;
    } catch (e) {
      console.warn(
        `[tick ${state.currentTick}] lumberjack-01 LLM call failed: ${e} — skipping tick`
      );
      return [];
    }
  }
}
