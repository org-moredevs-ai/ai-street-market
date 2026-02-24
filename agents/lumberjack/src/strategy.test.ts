import { describe, expect, it } from "vitest";
import type { AgentState, ObservedOffer } from "./state.js";
import { createInitialState } from "./state.js";
import { decideHardcoded as decide } from "./strategy.js";

function makeState(overrides: Partial<AgentState> = {}): AgentState {
  return {
    ...createInitialState("lumberjack-01"),
    joined: true,
    wallet: 100,
    currentTick: 5,
    ...overrides,
  };
}

describe("Lumberjack Gather", () => {
  it("gathers wood and nails from spawn", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 20, nails: 15, potato: 10 },
    });
    const actions = decide(state);
    const gathers = actions.filter((a) => a.kind === "gather");
    expect(gathers).toHaveLength(2);
    const items = new Set(gathers.map((a) => a.params.item));
    expect(items).toEqual(new Set(["wood", "nails"]));
  });

  it("gathers correct quantities", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 20, nails: 15 },
    });
    const actions = decide(state);
    const woodGather = actions.find(
      (a) => a.kind === "gather" && a.params.item === "wood"
    );
    const nailsGather = actions.find(
      (a) => a.kind === "gather" && a.params.item === "nails"
    );
    expect(woodGather?.params.quantity).toBe(8);
    expect(nailsGather?.params.quantity).toBe(5);
  });

  it("limits gather by available spawn", () => {
    const state = makeState({
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 3, nails: 1 },
    });
    const actions = decide(state);
    const woodGather = actions.find(
      (a) => a.kind === "gather" && a.params.item === "wood"
    );
    const nailsGather = actions.find(
      (a) => a.kind === "gather" && a.params.item === "nails"
    );
    expect(woodGather?.params.quantity).toBe(3);
    expect(nailsGather?.params.quantity).toBe(1);
  });

  it("skips gather without spawn", () => {
    const state = makeState({ currentSpawnId: null });
    const actions = decide(state);
    const gathers = actions.filter((a) => a.kind === "gather");
    expect(gathers).toHaveLength(0);
  });
});

describe("Lumberjack Crafting", () => {
  it("crafts shelf when has ingredients", () => {
    const state = makeState({ inventory: { wood: 5, nails: 3 } });
    const actions = decide(state);
    const crafts = actions.filter((a) => a.kind === "craft_start");
    expect(crafts).toHaveLength(1);
    expect(crafts[0].params.recipe).toBe("shelf");
  });

  it("does not craft without ingredients", () => {
    const state = makeState({ inventory: { wood: 2, nails: 1 } });
    const actions = decide(state);
    const crafts = actions.filter((a) => a.kind === "craft_start");
    expect(crafts).toHaveLength(0);
  });

  it("does not craft while already crafting", () => {
    const state = makeState({
      inventory: { wood: 5, nails: 3 },
      activeCraft: { recipe: "shelf", startedTick: 3, durationTicks: 3 },
    });
    const actions = decide(state);
    const crafts = actions.filter((a) => a.kind === "craft_start");
    expect(crafts).toHaveLength(0);
  });
});

describe("Lumberjack Sell", () => {
  it("offers shelf at 12.0", () => {
    const state = makeState({ inventory: { shelf: 2 } });
    const actions = decide(state);
    const offers = actions.filter((a) => a.kind === "offer");
    expect(offers).toHaveLength(1);
    expect(offers[0].params.item).toBe("shelf");
    expect(offers[0].params.quantity).toBe(2);
    expect(offers[0].params.price_per_unit).toBe(12.0);
  });

  it("no offer without shelf", () => {
    const state = makeState({ inventory: {} });
    const actions = decide(state);
    const offers = actions.filter((a) => a.kind === "offer");
    expect(offers).toHaveLength(0);
  });
});

describe("Lumberjack Accept Bids", () => {
  it("accepts bid at base price", () => {
    const bid: ObservedOffer = {
      msgId: "bid-1",
      fromAgent: "buyer-01",
      item: "shelf",
      quantity: 1,
      pricePerUnit: 10.0,
      isSell: false,
    };
    const state = makeState({ observedOffers: [bid] });
    const actions = decide(state);
    const accepts = actions.filter((a) => a.kind === "accept");
    expect(accepts).toHaveLength(1);
    expect(accepts[0].params.reference_msg_id).toBe("bid-1");
  });

  it("rejects bid below base price", () => {
    const bid: ObservedOffer = {
      msgId: "bid-1",
      fromAgent: "buyer-01",
      item: "shelf",
      quantity: 1,
      pricePerUnit: 8.0,
      isSell: false,
    };
    const state = makeState({ observedOffers: [bid] });
    const actions = decide(state);
    const accepts = actions.filter((a) => a.kind === "accept");
    expect(accepts).toHaveLength(0);
  });

  it("ignores sell offers", () => {
    const offer: ObservedOffer = {
      msgId: "off-1",
      fromAgent: "other",
      item: "shelf",
      quantity: 1,
      pricePerUnit: 15.0,
      isSell: true,
    };
    const state = makeState({ observedOffers: [offer] });
    const actions = decide(state);
    const accepts = actions.filter((a) => a.kind === "accept");
    expect(accepts).toHaveLength(0);
  });
});

describe("Lumberjack Budget", () => {
  it("respects action limit", () => {
    const state = makeState({
      actionsThisTick: 4,
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 20, nails: 15 },
      inventory: { wood: 5, nails: 3, shelf: 1 },
    });
    const actions = decide(state);
    expect(actions.length).toBeLessThanOrEqual(1);
  });

  it("returns empty when no budget", () => {
    const state = makeState({ actionsThisTick: 5 });
    const actions = decide(state);
    expect(actions).toHaveLength(0);
  });
});

describe("Lumberjack Energy", () => {
  it("consumes soup when energy low", () => {
    const state = makeState({ energy: 20, inventory: { soup: 1 } });
    const actions = decide(state);
    const consumes = actions.filter((a) => a.kind === "consume");
    expect(consumes).toHaveLength(1);
    expect(consumes[0].params.item).toBe("soup");
  });

  it("no consume when energy ok", () => {
    const state = makeState({ energy: 80, inventory: { soup: 1 } });
    const actions = decide(state);
    const consumes = actions.filter((a) => a.kind === "consume");
    expect(consumes).toHaveLength(0);
  });

  it("rest when critical — no gather or offer", () => {
    const state = makeState({
      energy: 5,
      inventory: { soup: 1, wood: 10 },
      currentSpawnId: "sp-1",
      currentSpawnItems: { wood: 15 },
    });
    const actions = decide(state);
    const kinds = new Set(actions.map((a) => a.kind));
    expect(kinds).not.toContain("gather");
    expect(kinds).not.toContain("offer");
    const consumes = actions.filter((a) => a.kind === "consume");
    expect(consumes).toHaveLength(1);
  });

  it("rest without soup — empty actions", () => {
    const state = makeState({ energy: 5, inventory: {} });
    const actions = decide(state);
    expect(actions).toHaveLength(0);
  });

  it("bids for soup when needed", () => {
    const state = makeState({ inventory: {} }); // no soup
    const actions = decide(state);
    const bids = actions.filter((a) => a.kind === "bid");
    expect(bids).toHaveLength(1);
    expect(bids[0].params.item).toBe("soup");
    expect(bids[0].params.quantity).toBe(2);
  });

  it("no bid when has soup", () => {
    const state = makeState({ inventory: { soup: 3 } });
    const actions = decide(state);
    const bids = actions.filter((a) => a.kind === "bid");
    expect(bids).toHaveLength(0);
  });

  it("no bid when soup offers visible", () => {
    const soupOffer: ObservedOffer = {
      msgId: "off-1",
      fromAgent: "chef-01",
      item: "soup",
      quantity: 5,
      pricePerUnit: 2.0,
      isSell: true,
    };
    const state = makeState({ inventory: {}, observedOffers: [soupOffer] });
    const actions = decide(state);
    const bids = actions.filter((a) => a.kind === "bid");
    expect(bids).toHaveLength(0);
  });

  it("accepts soup offer when available", () => {
    // Lumberjack doesn't auto-accept soup offers in strategy (could be added later)
    // but it does bid for soup — this test verifies the bid is suppressed when offers exist
    const soupOffer: ObservedOffer = {
      msgId: "off-1",
      fromAgent: "chef-01",
      item: "soup",
      quantity: 3,
      pricePerUnit: 2.5,
      isSell: true,
    };
    const state = makeState({ inventory: {}, observedOffers: [soupOffer] });
    const actions = decide(state);
    const bids = actions.filter(
      (a) => a.kind === "bid" && a.params.item === "soup"
    );
    expect(bids).toHaveLength(0);
  });
});
