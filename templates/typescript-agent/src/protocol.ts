/**
 * Protocol types for the AI Street Market.
 *
 * This is a standalone reimplementation — no Python SDK dependency.
 * See docs/PROTOCOL.md for the full specification.
 */

import { v4 as uuidv4 } from "uuid";

/** All message types in the protocol */
export const MessageType = {
  TICK: "tick",
  ENERGY_UPDATE: "energy_update",
  JOIN: "join",
  HEARTBEAT: "heartbeat",
  OFFER: "offer",
  BID: "bid",
  ACCEPT: "accept",
  COUNTER: "counter",
  SETTLEMENT: "settlement",
  SPAWN: "spawn",
  GATHER: "gather",
  GATHER_RESULT: "gather_result",
  CONSUME: "consume",
  CONSUME_RESULT: "consume_result",
  CRAFT_START: "craft_start",
  CRAFT_COMPLETE: "craft_complete",
  RENT_DUE: "rent_due",
  BANKRUPTCY: "bankruptcy",
  NATURE_EVENT: "nature_event",
  NARRATION: "narration",
  VALIDATION_RESULT: "validation_result",
} as const;

export type MessageTypeValue = (typeof MessageType)[keyof typeof MessageType];

/** The standard message envelope */
export interface Envelope {
  id: string;
  from: string;
  topic: string;
  timestamp: number;
  tick: number;
  type: MessageTypeValue;
  payload: Record<string, unknown>;
}

/** Topic path constants */
export const Topics = {
  TICK: "/system/tick",
  NATURE: "/world/nature",
  SQUARE: "/market/square",
  GOVERNANCE: "/market/governance",
  BANK: "/market/bank",
  RAW_GOODS: "/market/raw-goods",
  FOOD: "/market/food",
  MATERIALS: "/market/materials",
  HOUSING: "/market/housing",
  GENERAL: "/market/general",
  agentInbox: (agentId: string) => `/agent/${agentId}/inbox`,
} as const;

/** Create a new envelope */
export function createMessage(
  from: string,
  topic: string,
  type: MessageTypeValue,
  payload: Record<string, unknown>,
  tick: number
): Envelope {
  return {
    id: uuidv4(),
    from,
    topic,
    timestamp: Date.now() / 1000,
    tick,
    type,
    payload,
  };
}

/** Convert topic path to NATS subject: /market/raw-goods → market.raw-goods */
export function toNatsSubject(topic: string): string {
  return topic.replace(/^\//, "").replace(/\//g, ".");
}

/** Map item to its market topic */
const ITEM_CATEGORY: Record<string, string> = {
  potato: "raw",
  onion: "raw",
  wood: "raw",
  nails: "raw",
  stone: "raw",
  soup: "food",
  bread: "food",
  shelf: "material",
  wall: "material",
  furniture: "housing",
  house: "housing",
};

const CATEGORY_TOPIC: Record<string, string> = {
  raw: Topics.RAW_GOODS,
  food: Topics.FOOD,
  material: Topics.MATERIALS,
  housing: Topics.HOUSING,
};

export function topicForItem(item: string): string {
  const cat = ITEM_CATEGORY[item];
  if (!cat) throw new Error(`Unknown item: ${item}`);
  const topic = CATEGORY_TOPIC[cat];
  if (!topic) throw new Error(`Unknown category: ${cat}`);
  return topic;
}
