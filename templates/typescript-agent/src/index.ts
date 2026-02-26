/**
 * AI Street Market Agent — TypeScript template.
 *
 * Standalone agent that connects to NATS, joins the economy,
 * gathers potatoes, and sells surplus. No Python SDK needed.
 *
 * See docs/PROTOCOL.md for the full protocol specification.
 */

import {
  connect,
  type NatsConnection,
  type JetStreamClient,
  type JetStreamManager,
  DeliverPolicy,
  AckPolicy,
  type ConsumerConfig,
} from "nats";
import {
  createMessage,
  type Envelope,
  MessageType,
  toNatsSubject,
  Topics,
  topicForItem,
} from "./protocol.js";
import {
  addInventory,
  advanceTick,
  type AgentState,
  createInitialState,
  needsHeartbeat,
  remainingActions,
  removeInventory,
} from "./state.js";
import { decide, type Action } from "./strategy.js";

// --- Configuration ---
const AGENT_ID = "my-ts-agent-01";
const AGENT_NAME = "My TS Agent";
const AGENT_DESCRIPTION = "Gathers potatoes and sells them on the market";
const NATS_URL = process.env.NATS_URL ?? "nats://localhost:4222";

const state: AgentState = createInitialState(AGENT_ID);
let nc: NatsConnection;
let js: JetStreamClient;

// --- Message Publishing ---

async function publishMessage(
  topic: string,
  type: string,
  payload: Record<string, unknown>
): Promise<Envelope> {
  const msg = createMessage(
    AGENT_ID,
    topic,
    type as Envelope["type"],
    payload,
    state.currentTick
  );
  const subject = toNatsSubject(topic);
  const data = JSON.stringify(msg);
  await js.publish(subject, new TextEncoder().encode(data));
  return msg;
}

// --- Action Execution ---

async function executeAction(action: Action): Promise<void> {
  switch (action.kind) {
    case "join": {
      await publishMessage(Topics.SQUARE, MessageType.JOIN, {
        agent_id: AGENT_ID,
        name: AGENT_NAME,
        description: AGENT_DESCRIPTION,
      });
      state.joined = true;
      state.wallet = 100.0;
      console.log(`[tick ${state.currentTick}] ${AGENT_ID}: joined the market`);
      break;
    }

    case "heartbeat": {
      const total = Object.values(state.inventory).reduce((s, v) => s + v, 0);
      await publishMessage(Topics.SQUARE, MessageType.HEARTBEAT, {
        agent_id: AGENT_ID,
        wallet: state.wallet,
        inventory_count: total,
      });
      state.lastHeartbeatTick = state.currentTick;
      state.actionsThisTick++;
      break;
    }

    case "gather": {
      const spawnId =
        (action.params.spawn_id as string) ?? state.currentSpawnId;
      if (!spawnId) return;
      await publishMessage(Topics.NATURE, MessageType.GATHER, {
        spawn_id: spawnId,
        item: action.params.item,
        quantity: action.params.quantity,
      });
      state.actionsThisTick++;
      break;
    }

    case "offer": {
      const item = action.params.item as string;
      const topic = topicForItem(item);
      await publishMessage(topic, MessageType.OFFER, {
        item,
        quantity: action.params.quantity,
        price_per_unit: action.params.price_per_unit,
      });
      state.actionsThisTick++;
      break;
    }

    case "bid": {
      const item = action.params.item as string;
      const topic = topicForItem(item);
      await publishMessage(topic, MessageType.BID, {
        item,
        quantity: action.params.quantity,
        max_price_per_unit: action.params.max_price_per_unit,
      });
      state.actionsThisTick++;
      break;
    }

    case "accept": {
      const topic = (action.params.topic as string) ?? Topics.SQUARE;
      await publishMessage(topic, MessageType.ACCEPT, {
        reference_msg_id: action.params.reference_msg_id,
        quantity: action.params.quantity,
      });
      state.actionsThisTick++;
      break;
    }

    case "consume": {
      await publishMessage(Topics.FOOD, MessageType.CONSUME, {
        item: action.params.item,
        quantity: action.params.quantity,
      });
      state.actionsThisTick++;
      break;
    }
  }
}

// --- Message Handlers ---

function handleSpawn(payload: Record<string, unknown>): void {
  state.currentSpawnId = payload.spawn_id as string;
  state.currentSpawnItems = { ...(payload.items as Record<string, number>) };
}

function handleGatherResult(payload: Record<string, unknown>): void {
  if (payload.agent_id === AGENT_ID && payload.success) {
    addInventory(state, payload.item as string, payload.quantity as number);
    console.log(
      `[tick ${state.currentTick}] ${AGENT_ID}: gathered ${payload.quantity} ${payload.item}`
    );
  }
}

function handleMarketMessage(envelope: Envelope): void {
  if (envelope.from === AGENT_ID) return;

  if (envelope.type === MessageType.OFFER) {
    state.observedOffers.push({
      msgId: envelope.id,
      fromAgent: envelope.from,
      item: envelope.payload.item as string,
      quantity: envelope.payload.quantity as number,
      pricePerUnit: envelope.payload.price_per_unit as number,
      isSell: true,
      tick: state.currentTick,
    });
  } else if (envelope.type === MessageType.BID) {
    state.observedOffers.push({
      msgId: envelope.id,
      fromAgent: envelope.from,
      item: envelope.payload.item as string,
      quantity: envelope.payload.quantity as number,
      pricePerUnit: envelope.payload.max_price_per_unit as number,
      isSell: false,
      tick: state.currentTick,
    });
  } else if (envelope.type === MessageType.SETTLEMENT) {
    const p = envelope.payload;
    if (p.buyer === AGENT_ID) {
      state.wallet -= p.total_price as number;
      addInventory(state, p.item as string, p.quantity as number);
    } else if (p.seller === AGENT_ID) {
      state.wallet += p.total_price as number;
      removeInventory(state, p.item as string, p.quantity as number);
    }
  }
}

// --- Tick Handler ---

async function onTick(tickNumber: number): Promise<void> {
  advanceTick(state, tickNumber);

  // Auto-join on first tick
  if (!state.joined) {
    await executeAction({ kind: "join", params: {} });
    await executeAction({ kind: "heartbeat", params: {} });
  }

  // Auto-heartbeat every 5 ticks
  if (needsHeartbeat(state)) {
    await executeAction({ kind: "heartbeat", params: {} });
  }

  // Run strategy
  const actions = decide(state);

  // Expire old observed offers (keep last 5 ticks)
  state.observedOffers = state.observedOffers.filter(
    (o) => o.tick >= tickNumber - 5
  );

  for (const action of actions) {
    if (remainingActions(state) <= 0) break;
    await executeAction(action);
  }
}

// --- Main ---

async function main(): Promise<void> {
  console.log(`${AGENT_NAME} connecting to ${NATS_URL}...`);
  nc = await connect({ servers: NATS_URL });
  js = nc.jetstream();
  const jsm: JetStreamManager = await nc.jetstreamManager();

  const decoder = new TextDecoder();

  // Helper: subscribe via JetStream ephemeral consumer
  async function subscribe(
    topic: string,
    handler: (envelope: Envelope) => void | Promise<void>
  ): Promise<void> {
    const subject = toNatsSubject(topic);
    const ci = await jsm.consumers.add("STREETMARKET", {
      filter_subject: subject,
      deliver_policy: DeliverPolicy.New,
      ack_policy: AckPolicy.Explicit,
    } as Partial<ConsumerConfig>);
    const consumer = await js.consumers.get("STREETMARKET", ci.name);
    const messages = await consumer.consume();
    (async () => {
      for await (const msg of messages) {
        try {
          const envelope: Envelope = JSON.parse(decoder.decode(msg.data));
          await handler(envelope);
        } catch (e) {
          console.error(`Error handling message on ${subject}:`, e);
        }
        msg.ack();
      }
    })();
  }

  // Subscribe to tick + energy updates
  await subscribe(Topics.TICK, async (env) => {
    if (env.type === MessageType.TICK) {
      await onTick(env.payload.tick_number as number);
    } else if (env.type === MessageType.ENERGY_UPDATE) {
      const levels = env.payload.energy_levels as Record<string, number>;
      if (AGENT_ID in levels) {
        state.energy = levels[AGENT_ID];
      }
    }
  });

  // Subscribe to nature (spawns + gather results)
  await subscribe(Topics.NATURE, (env) => {
    if (env.type === MessageType.SPAWN) {
      handleSpawn(env.payload);
    } else if (env.type === MessageType.GATHER_RESULT) {
      handleGatherResult(env.payload);
    }
  });

  // Subscribe to all market topics
  await subscribe("/market/>", handleMarketMessage);

  console.log(`${AGENT_NAME} running — press Ctrl+C to stop`);

  // Graceful shutdown
  process.on("SIGINT", async () => {
    console.log(`\n${AGENT_NAME} shutting down...`);
    await nc.drain();
    process.exit(0);
  });
  process.on("SIGTERM", async () => {
    await nc.drain();
    process.exit(0);
  });

  // Keep alive
  await nc.closed();
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
