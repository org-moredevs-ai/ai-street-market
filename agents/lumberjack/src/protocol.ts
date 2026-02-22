/**
 * Minimal re-implementation of the AI Street Market envelope protocol.
 * Proves any language with a NATS client can participate.
 */

import { v4 as uuidv4 } from "uuid";

/** Message types used by the Lumberjack */
export const MessageType = {
  TICK: "tick",
  SPAWN: "spawn",
  GATHER: "gather",
  GATHER_RESULT: "gather_result",
  JOIN: "join",
  HEARTBEAT: "heartbeat",
  OFFER: "offer",
  BID: "bid",
  ACCEPT: "accept",
  SETTLEMENT: "settlement",
  CRAFT_START: "craft_start",
  CRAFT_COMPLETE: "craft_complete",
} as const;

export type MessageTypeValue = (typeof MessageType)[keyof typeof MessageType];

/** The standard message envelope — matches Python Envelope JSON schema */
export interface Envelope {
  id: string;
  from: string;
  topic: string;
  timestamp: number;
  tick: number;
  type: MessageTypeValue;
  payload: Record<string, unknown>;
}

/** Topic path constants matching Python Topics class */
export const Topics = {
  NATURE: "/world/nature",
  SQUARE: "/market/square",
  GOVERNANCE: "/market/governance",
  BANK: "/market/bank",
  RAW_GOODS: "/market/raw-goods",
  FOOD: "/market/food",
  MATERIALS: "/market/materials",
  HOUSING: "/market/housing",
  GENERAL: "/market/general",
  TICK: "/system/tick",
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

/** Convert a topic path to a NATS subject: /market/raw-goods → market.raw-goods */
export function toNatsSubject(topic: string): string {
  return topic.replace(/^\//, "").replace(/\//g, ".");
}

/** Map item name to market topic */
const ITEM_CATEGORY: Record<string, string> = {
  potato: "raw",
  onion: "raw",
  wood: "raw",
  nails: "raw",
  stone: "raw",
  soup: "food",
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
