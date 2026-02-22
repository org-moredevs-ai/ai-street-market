/**
 * Lumberjack Agent — TypeScript entry point.
 * Connects to NATS, subscribes to tick/nature/market, runs decide() loop.
 */

import {
  connect,
  type NatsConnection,
  type JetStreamClient,
  type ConsumerConfig,
  DeliverPolicy,
  AckPolicy,
  type JetStreamManager,
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
  craftIsDone,
  createInitialState,
  needsHeartbeat,
  removeInventory,
  remainingActions,
} from "./state.js";
import { decide, type Action } from "./strategy.js";

const AGENT_ID = "lumberjack-01";
const AGENT_NAME = "Jack Lumber";
const AGENT_DESCRIPTION =
  "Gathers wood and nails, crafts shelves, sells on the materials market";

const NATS_URL = process.env.NATS_URL ?? "nats://localhost:4222";

// Shelf recipe constants (matching Python catalogue)
const SHELF_RECIPE = {
  inputs: { wood: 3, nails: 2 } as Record<string, number>,
  output: "shelf",
  outputQuantity: 1,
  ticks: 3,
};

const state: AgentState = createInitialState(AGENT_ID);

let nc: NatsConnection;
let js: JetStreamClient;

async function publishMessage(
  topic: string,
  type: string,
  payload: Record<string, unknown>
): Promise<Envelope> {
  const msg = createMessage(AGENT_ID, topic, type as Envelope["type"], payload, state.currentTick);
  const subject = toNatsSubject(topic);
  const data = JSON.stringify(msg);
  await js.publish(subject, new TextEncoder().encode(data));
  return msg;
}

async function executeAction(action: Action): Promise<void> {
  const tick = state.currentTick;

  switch (action.kind) {
    case "join": {
      await publishMessage(Topics.SQUARE, MessageType.JOIN, {
        agent_id: AGENT_ID,
        name: AGENT_NAME,
        description: AGENT_DESCRIPTION,
      });
      state.joined = true;
      state.wallet = 100.0;
      console.log(`[tick ${tick}] ${AGENT_ID}: joined the market`);
      break;
    }

    case "heartbeat": {
      const total = Object.values(state.inventory).reduce((s, v) => s + v, 0);
      await publishMessage(Topics.SQUARE, MessageType.HEARTBEAT, {
        agent_id: AGENT_ID,
        wallet: state.wallet,
        inventory_count: total,
      });
      state.lastHeartbeatTick = tick;
      state.actionsThisTick++;
      break;
    }

    case "gather": {
      const spawnId = (action.params.spawn_id as string) ?? state.currentSpawnId;
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
      const msg = await publishMessage(topic, MessageType.OFFER, {
        item,
        quantity: action.params.quantity,
        price_per_unit: action.params.price_per_unit,
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

    case "craft_start": {
      const recipeName = action.params.recipe as string;
      // Deduct inputs
      for (const [item, qty] of Object.entries(SHELF_RECIPE.inputs)) {
        removeInventory(state, item, qty);
      }
      const topic = topicForItem(SHELF_RECIPE.output);
      await publishMessage(topic, MessageType.CRAFT_START, {
        recipe: recipeName,
        inputs: { ...SHELF_RECIPE.inputs },
        estimated_ticks: SHELF_RECIPE.ticks,
      });
      state.activeCraft = {
        recipe: recipeName,
        startedTick: tick,
        durationTicks: SHELF_RECIPE.ticks,
      };
      state.actionsThisTick++;
      break;
    }

    case "craft_complete": {
      const recipe = action.params.recipe as string;
      const topic = topicForItem(SHELF_RECIPE.output);
      await publishMessage(topic, MessageType.CRAFT_COMPLETE, {
        recipe,
        output: { [SHELF_RECIPE.output]: SHELF_RECIPE.outputQuantity },
        agent: AGENT_ID,
      });
      addInventory(state, SHELF_RECIPE.output, SHELF_RECIPE.outputQuantity);
      state.activeCraft = null;
      state.actionsThisTick++;
      break;
    }
  }
}

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
    });
  } else if (envelope.type === MessageType.BID) {
    state.observedOffers.push({
      msgId: envelope.id,
      fromAgent: envelope.from,
      item: envelope.payload.item as string,
      quantity: envelope.payload.quantity as number,
      pricePerUnit: envelope.payload.max_price_per_unit as number,
      isSell: false,
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

async function onTick(tickNumber: number): Promise<void> {
  advanceTick(state, tickNumber);

  // Auto-join
  if (!state.joined) {
    await executeAction({ kind: "join", params: {} });
  }

  // Auto-heartbeat
  if (needsHeartbeat(state)) {
    await executeAction({ kind: "heartbeat", params: {} });
  }

  // Auto-craft-complete
  if (state.activeCraft && craftIsDone(state.activeCraft, tickNumber)) {
    await executeAction({
      kind: "craft_complete",
      params: { recipe: state.activeCraft.recipe },
    });
  }

  // Run strategy
  const actions = decide(state);
  for (const action of actions) {
    if (remainingActions(state) <= 0) break;
    await executeAction(action);
  }
}

async function main(): Promise<void> {
  console.log(`${AGENT_NAME} connecting to ${NATS_URL}...`);
  nc = await connect({ servers: NATS_URL });
  js = nc.jetstream();
  const jsm: JetStreamManager = await nc.jetstreamManager();

  const decoder = new TextDecoder();

  // Helper to subscribe via JetStream ephemeral consumer
  async function subscribe(
    topic: string,
    handler: (envelope: Envelope) => void | Promise<void>
  ): Promise<void> {
    const subject = toNatsSubject(topic);
    const consumers = await jsm.consumers;
    const consumer = await consumers.add("STREETMARKET", {
      filter_subject: subject,
      deliver_policy: DeliverPolicy.New,
      ack_policy: AckPolicy.Explicit,
    } as Partial<ConsumerConfig>);
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

  // Subscribe to tick
  await subscribe(Topics.TICK, async (env) => {
    if (env.type === MessageType.TICK) {
      await onTick(env.payload.tick_number as number);
    }
  });

  // Subscribe to nature (spawn + gather results)
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
