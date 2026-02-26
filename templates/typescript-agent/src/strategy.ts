/**
 * Strategy — the brain of your agent.
 *
 * Implement decide() to return a list of actions.
 * This template gathers potatoes and sells surplus at a profit.
 */

import type { AgentState } from "./state.js";
import { inventoryCount } from "./state.js";

export interface Action {
  kind: string;
  params: Record<string, unknown>;
}

export function decide(state: AgentState): Action[] {
  const actions: Action[] = [];

  // 1. Gather potatoes if a spawn is available
  if (state.currentSpawnId && state.energy >= 10) {
    const available = state.currentSpawnItems["potato"] ?? 0;
    if (available > 0) {
      const qty = Math.min(available, 3);
      actions.push({
        kind: "gather",
        params: {
          spawn_id: state.currentSpawnId,
          item: "potato",
          quantity: qty,
        },
      });
    }
  }

  // 2. Sell surplus potatoes (keep 5 in reserve)
  const potatoes = inventoryCount(state, "potato");
  if (potatoes > 5) {
    actions.push({
      kind: "offer",
      params: {
        item: "potato",
        quantity: potatoes - 5,
        price_per_unit: 2.5,
      },
    });
  }

  // 3. Accept bids for potatoes at a good price
  for (const offer of state.observedOffers) {
    if (!offer.isSell && offer.item === "potato" && offer.pricePerUnit >= 2.0) {
      const acceptQty = Math.min(
        offer.quantity,
        inventoryCount(state, "potato") - 5
      );
      if (acceptQty > 0) {
        actions.push({
          kind: "accept",
          params: {
            reference_msg_id: offer.msgId,
            quantity: acceptQty,
            topic: "/market/raw-goods",
          },
        });
        break; // One accept per tick
      }
    }
  }

  return actions;
}
