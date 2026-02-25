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

const MARKET_RULES = `You are a trading agent in the AI Street Market — a tick-based economy.

## Rules
- Up to 5 actions per tick. Energy: max 100, +5/tick. Costs: gather=10, craft=15, trade=5.
- Food restores energy: soup=+30, bread=+20. Wallet starts at 100. Rent: 2/tick after tick 20.

## Items
Raw (from nature): potato(2$), onion(2$), wood(3$), nails(1$), stone(4$)
Recipes: shelf=wood×3+nails×2(3 ticks,10$)

## CRITICAL: You MUST trade to survive!
- If you have surplus items → post an OFFER to sell them
- If you need items you can't gather → post a BID to buy them
- If you see a good offer → ACCEPT it

## Actions (JSON params)
- gather: {"spawn_id":"...","item":"...","quantity":N}
- offer: {"item":"...","quantity":N,"price_per_unit":N.N}
- bid: {"item":"...","quantity":N,"max_price_per_unit":N.N}
- accept: {"reference_msg_id":"...","quantity":N,"topic":"..."}
- craft_start: {"recipe":"..."}
- consume: {"item":"...","quantity":1}

## Response: ONLY JSON, no other text
Example — gather and sell:
{"reasoning":"Have wood surplus, selling 2","actions":[{"kind":"gather","params":{"spawn_id":"abc","item":"wood","quantity":2}},{"kind":"offer","params":{"item":"wood","quantity":2,"price_per_unit":3.5}}]}

Skip tick: {"reasoning":"Nothing to do","actions":[]}`;

export const LUMBERJACK_PERSONA = `You are Jack Lumber — you gather wood and nails, craft shelves, sell them.
EVERY TICK you should:
1. Gather from nature if spawn available (wood first, then nails)
2. OFFER to sell ANY wood above 4 (keep only 4 reserve). Price: 3.5/unit
3. OFFER to sell ANY nails above 3 (keep only 3 reserve). Price: 1.5/unit
4. craft_start shelf when you have 3+ wood AND 2+ nails and NOT crafting
5. OFFER to sell shelf (price: 12.0) when you have 1+ shelf
6. BID for soup (quantity:1, max_price:10.0) when energy < 40 and no soup in inventory
7. Eat soup/bread when energy < 30
IMPORTANT: If you have 5+ wood, you MUST post an offer to sell!`;

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

const LLM_TIMEOUT = 15000; // ms
// Set to 0 for free-tier models (tight rate limits); increase for paid models.
const LLM_MAX_RETRIES = 0;

/**
 * Extract a JSON object from raw LLM text output.
 * Handles: pure JSON, markdown code blocks, JSON embedded in text.
 */
export function extractJson(text: string): Record<string, unknown> {
  text = text.trim();

  // Try direct JSON parse
  try {
    return JSON.parse(text);
  } catch {
    // continue
  }

  // Try markdown code block
  const codeMatch = text.match(/```(?:json)?\s*\n?([\s\S]*?)\n?\s*```/);
  if (codeMatch) {
    try {
      return JSON.parse(codeMatch[1]);
    } catch {
      // continue
    }
  }

  // Find first { to last }
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1));
    } catch {
      // continue
    }
  }

  throw new Error(
    `Could not extract JSON from LLM response: ${text.slice(0, 200)}`
  );
}

export class LumberjackLLMBrain {
  private systemPrompt: string;
  private llm: ChatOpenAI | null = null;

  constructor() {
    this.systemPrompt =
      MARKET_RULES + "\n\n## Your Role\n" + LUMBERJACK_PERSONA;
  }

  private getLlm(): ChatOpenAI {
    if (!this.llm) {
      const config = loadConfig();
      if (!config.apiKey) {
        throw new Error("No API key configured");
      }
      this.llm = new ChatOpenAI({
        model: config.model,
        apiKey: config.apiKey,
        configuration: { baseURL: config.apiBase },
        maxTokens: config.maxTokens,
        temperature: config.temperature,
      });
    }
    return this.llm;
  }

  async decide(state: AgentState): Promise<Action[]> {
    let lastError: unknown = null;
    const messages = [
      new SystemMessage(this.systemPrompt),
      new HumanMessage(serializeState(state)),
    ];

    for (let attempt = 0; attempt <= LLM_MAX_RETRIES; attempt++) {
      try {
        const llm = this.getLlm();

        const response = await Promise.race([
          llm.invoke(messages),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error("LLM timeout")), LLM_TIMEOUT)
          ),
        ]);

        const rawText =
          typeof response.content === "string"
            ? response.content
            : String(response.content);
        if (!rawText.trim()) {
          throw new Error("Empty response from LLM");
        }

        const data = extractJson(rawText);
        const plan = ActionPlanSchema.parse(data);
        const actions = validatePlan(plan, state);

        if (actions.length > 0) {
          console.log(
            `[tick ${state.currentTick}] lumberjack-01 reasoning: ${plan.reasoning.slice(0, 80)} → ${actions.length} actions`
          );
        }

        return actions;
      } catch (e) {
        lastError = e;
        if (attempt < LLM_MAX_RETRIES) {
          console.debug(
            `[tick ${state.currentTick}] lumberjack-01 LLM attempt ${attempt + 1} failed: ${e} — retrying`
          );
        }
      }
    }

    console.warn(
      `[tick ${state.currentTick}] lumberjack-01 LLM failed after ${1 + LLM_MAX_RETRIES} attempts: ${lastError} — skipping tick`
    );
    return [];
  }
}
