import { describe, expect, it } from "vitest";
import type { AgentState, ObservedOffer } from "./state.js";
import { createInitialState } from "./state.js";
import {
  loadConfig,
  serializeState,
  validateAction,
  validatePlan,
  LUMBERJACK_PERSONA,
} from "./llm_brain.js";

function makeState(overrides: Partial<AgentState> = {}): AgentState {
  return {
    ...createInitialState("lumberjack-01"),
    joined: true,
    wallet: 100,
    currentTick: 5,
    energy: 80,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Config tests
// ---------------------------------------------------------------------------

describe("LLMConfig", () => {
  it("loads default config from env", () => {
    process.env.OPENROUTER_API_KEY = "test-key";
    process.env.DEFAULT_MODEL = "test-model";
    const config = loadConfig();
    expect(config.apiKey).toBe("test-key");
    expect(config.model).toBe("test-model");
    delete process.env.OPENROUTER_API_KEY;
    delete process.env.DEFAULT_MODEL;
  });

  it("uses per-agent model override", () => {
    process.env.OPENROUTER_API_KEY = "test-key";
    process.env.LUMBERJACK_MODEL = "custom-model";
    process.env.DEFAULT_MODEL = "default-model";
    const config = loadConfig();
    expect(config.model).toBe("custom-model");
    delete process.env.OPENROUTER_API_KEY;
    delete process.env.LUMBERJACK_MODEL;
    delete process.env.DEFAULT_MODEL;
  });
});

// ---------------------------------------------------------------------------
// Serialize state tests
// ---------------------------------------------------------------------------

describe("serializeState", () => {
  it("includes tick, wallet, energy", () => {
    const state = makeState({ currentTick: 10, wallet: 85.5, energy: 60 });
    const text = serializeState(state);
    expect(text).toContain("Tick: 10");
    expect(text).toContain("Wallet: 85.5");
    expect(text).toContain("Energy: 60/100");
  });

  it("shows inventory items", () => {
    const state = makeState({ inventory: { wood: 5, nails: 3 } });
    const text = serializeState(state);
    expect(text).toContain("wood: 5");
    expect(text).toContain("nails: 3");
  });

  it("shows empty inventory", () => {
    const state = makeState({ inventory: {} });
    const text = serializeState(state);
    expect(text).toContain("Inventory: empty");
  });

  it("shows spawn info", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 10, nails: 5 },
    });
    const text = serializeState(state);
    expect(text).toContain("sp-1");
    expect(text).toContain("wood: 10");
  });

  it("shows no spawn", () => {
    const state = makeState({ currentSpawnId: null });
    const text = serializeState(state);
    expect(text).toContain("Nature spawn: none");
  });

  it("shows crafting status", () => {
    const state = makeState({
      activeCraft: { recipe: "shelf", startedTick: 3, durationTicks: 3 },
    });
    const text = serializeState(state);
    expect(text).toContain("Crafting: shelf");
  });

  it("shows observed offers", () => {
    const obs: ObservedOffer = {
      msgId: "msg-1",
      fromAgent: "chef-01",
      item: "soup",
      quantity: 2,
      pricePerUnit: 8.0,
      isSell: true,
    };
    const state = makeState({ observedOffers: [obs] });
    const text = serializeState(state);
    expect(text).toContain("chef-01");
    expect(text).toContain("SELLING");
    expect(text).toContain("msg-1");
  });
});

// ---------------------------------------------------------------------------
// Validate action tests
// ---------------------------------------------------------------------------

describe("validateAction", () => {
  it("validates gather action", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 10 },
    });
    const result = validateAction(
      { kind: "gather", params: { spawn_id: "sp-1", item: "wood", quantity: 5 } },
      state
    );
    expect(result).not.toBeNull();
    expect(result!.kind).toBe("gather");
    expect(result!.params.quantity).toBe(5);
  });

  it("clamps gather quantity to available", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 3 },
    });
    const result = validateAction(
      { kind: "gather", params: { spawn_id: "sp-1", item: "wood", quantity: 100 } },
      state
    );
    expect(result).not.toBeNull();
    expect(result!.params.quantity).toBe(3);
  });

  it("rejects gather with no spawn", () => {
    const state = makeState({ currentSpawnId: null });
    const result = validateAction(
      { kind: "gather", params: { item: "wood", quantity: 5 } },
      state
    );
    expect(result).toBeNull();
  });

  it("validates offer action", () => {
    const state = makeState({ inventory: { shelf: 2 } });
    const result = validateAction(
      { kind: "offer", params: { item: "shelf", quantity: 1, price_per_unit: 12 } },
      state
    );
    expect(result).not.toBeNull();
    expect(result!.kind).toBe("offer");
  });

  it("rejects offer with insufficient inventory", () => {
    const state = makeState({ inventory: {} });
    const result = validateAction(
      { kind: "offer", params: { item: "shelf", quantity: 1, price_per_unit: 12 } },
      state
    );
    expect(result).toBeNull();
  });

  it("validates bid action", () => {
    const state = makeState();
    const result = validateAction(
      { kind: "bid", params: { item: "soup", quantity: 2, max_price_per_unit: 3 } },
      state
    );
    expect(result).not.toBeNull();
    expect(result!.kind).toBe("bid");
  });

  it("validates accept action with matching offer", () => {
    const obs: ObservedOffer = {
      msgId: "msg-1",
      fromAgent: "buyer-01",
      item: "shelf",
      quantity: 1,
      pricePerUnit: 10,
      isSell: false,
    };
    const state = makeState({ observedOffers: [obs] });
    const result = validateAction(
      {
        kind: "accept",
        params: { reference_msg_id: "msg-1", quantity: 1, topic: "/market/materials" },
      },
      state
    );
    expect(result).not.toBeNull();
  });

  it("rejects accept with unknown msg_id", () => {
    const state = makeState({ observedOffers: [] });
    const result = validateAction(
      {
        kind: "accept",
        params: { reference_msg_id: "msg-999", quantity: 1, topic: "/market/materials" },
      },
      state
    );
    expect(result).toBeNull();
  });

  it("validates craft_start for shelf", () => {
    const state = makeState({ inventory: { wood: 5, nails: 3 } });
    const result = validateAction(
      { kind: "craft_start", params: { recipe: "shelf" } },
      state
    );
    expect(result).not.toBeNull();
  });

  it("rejects craft_start without ingredients", () => {
    const state = makeState({ inventory: { wood: 1 } });
    const result = validateAction(
      { kind: "craft_start", params: { recipe: "shelf" } },
      state
    );
    expect(result).toBeNull();
  });

  it("rejects non-shelf recipes", () => {
    const state = makeState({ inventory: { potato: 5, onion: 3 } });
    const result = validateAction(
      { kind: "craft_start", params: { recipe: "soup" } },
      state
    );
    expect(result).toBeNull();
  });

  it("validates consume action", () => {
    const state = makeState({ inventory: { soup: 1 } });
    const result = validateAction(
      { kind: "consume", params: { item: "soup" } },
      state
    );
    expect(result).not.toBeNull();
  });

  it("rejects consume non-food", () => {
    const state = makeState({ inventory: { wood: 5 } });
    const result = validateAction(
      { kind: "consume", params: { item: "wood" } },
      state
    );
    expect(result).toBeNull();
  });

  it("rejects invalid action kind", () => {
    const state = makeState();
    const result = validateAction(
      { kind: "teleport", params: {} },
      state
    );
    expect(result).toBeNull();
  });

  it("rejects action with insufficient energy", () => {
    const state = makeState({
      energy: 3,
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 10 },
    });
    const result = validateAction(
      { kind: "gather", params: { spawn_id: "sp-1", item: "wood", quantity: 5 } },
      state
    );
    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Validate plan tests
// ---------------------------------------------------------------------------

describe("validatePlan", () => {
  it("filters invalid actions", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 10 },
    });
    const plan = {
      reasoning: "test",
      actions: [
        { kind: "gather", params: { spawn_id: "sp-1", item: "wood", quantity: 5 } },
        { kind: "teleport", params: {} },
        { kind: "bid", params: { item: "soup", quantity: 1, max_price_per_unit: 3 } },
      ],
    };
    const actions = validatePlan(plan, state);
    expect(actions).toHaveLength(2);
  });

  it("respects action budget", () => {
    const state = makeState({
      actionsThisTick: 4,
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 10 },
    });
    const plan = {
      reasoning: "test",
      actions: [
        { kind: "gather", params: { spawn_id: "sp-1", item: "wood", quantity: 5 } },
        { kind: "bid", params: { item: "soup", quantity: 1, max_price_per_unit: 3 } },
      ],
    };
    const actions = validatePlan(plan, state);
    expect(actions).toHaveLength(1);
  });

  it("handles empty plan", () => {
    const state = makeState();
    const plan = { reasoning: "skip", actions: [] };
    const actions = validatePlan(plan, state);
    expect(actions).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Persona test
// ---------------------------------------------------------------------------

describe("LUMBERJACK_PERSONA", () => {
  it("exists and mentions Jack Lumber", () => {
    expect(LUMBERJACK_PERSONA).toContain("Jack Lumber");
    expect(LUMBERJACK_PERSONA).toContain("wood");
    expect(LUMBERJACK_PERSONA).toContain("shelf");
  });
});
