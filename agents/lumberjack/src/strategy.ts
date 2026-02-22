/**
 * Lumberjack strategy — pure function, no I/O.
 *
 * Priority order each tick:
 * 1. GATHER wood(8) + nails(5) from current spawn
 * 2. CRAFT_START shelf if has wood>=3 + nails>=2 and not crafting
 * 3. OFFER shelf at 12.0 on /market/materials
 * 4. ACCEPT BIDs for shelf at >= base_price (10.0)
 */

import { topicForItem } from "./protocol.js";
import {
  type AgentState,
  hasItems,
  inventoryCount,
  isCrafting,
  remainingActions,
} from "./state.js";

export interface Action {
  kind: string;
  params: Record<string, unknown>;
}

/** Items the lumberjack gathers each tick */
const GATHER_PLAN: [string, number][] = [
  ["wood", 8],
  ["nails", 5],
];

/** Shelf recipe inputs */
const SHELF_INPUTS: Record<string, number> = { wood: 3, nails: 2 };

/** Shelf selling price */
const SHELF_SELL_PRICE = 12.0;

/** Minimum price to accept for shelf (base_price) */
const SHELF_BASE_PRICE = 10.0;

export function decide(state: AgentState): Action[] {
  const actions: Action[] = [];
  let budget = remainingActions(state);

  // 1. GATHER from current spawn
  if (state.currentSpawnId) {
    for (const [item, qty] of GATHER_PLAN) {
      if (budget <= 0) break;
      const available = state.currentSpawnItems[item] ?? 0;
      if (available > 0) {
        const gatherQty = Math.min(qty, available);
        actions.push({
          kind: "gather",
          params: {
            spawn_id: state.currentSpawnId,
            item,
            quantity: gatherQty,
          },
        });
        budget--;
      }
    }
  }

  // 2. CRAFT_START shelf if we have ingredients and not crafting
  if (budget > 0 && !isCrafting(state) && hasItems(state, SHELF_INPUTS)) {
    actions.push({
      kind: "craft_start",
      params: { recipe: "shelf" },
    });
    budget--;
  }

  // 3. OFFER shelf if we have any
  if (budget > 0 && inventoryCount(state, "shelf") > 0) {
    actions.push({
      kind: "offer",
      params: {
        item: "shelf",
        quantity: inventoryCount(state, "shelf"),
        price_per_unit: SHELF_SELL_PRICE,
      },
    });
    budget--;
  }

  // 4. ACCEPT BIDs for shelf at >= base_price
  for (const obs of state.observedOffers) {
    if (budget <= 0) break;
    if (obs.isSell) continue; // Only accept buy bids
    if (obs.item !== "shelf") continue;
    if (obs.pricePerUnit >= SHELF_BASE_PRICE) {
      const topic = topicForItem(obs.item);
      actions.push({
        kind: "accept",
        params: {
          reference_msg_id: obs.msgId,
          quantity: obs.quantity,
          topic,
        },
      });
      budget--;
    }
  }

  return actions;
}
