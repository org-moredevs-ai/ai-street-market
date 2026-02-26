/**
 * Minimal TypeScript trading agent template — copy and customize.
 *
 * This connects to NATS, joins the market, and processes messages.
 * Replace the onTick() and onMarketMessage() logic with your strategy.
 *
 * Requirements:
 *   npm install nats
 *
 * Environment variables:
 *   NATS_URL=nats://localhost:4222
 *
 * Usage:
 *   npx tsx my_agent.ts
 */

import { connect, type NatsConnection, type JetStreamClient, type Msg } from "nats";

const AGENT_ID = "my-ts-agent";
const DISPLAY_NAME = "My TypeScript Agent";

// Topics
const Topics = {
  SQUARE: "market.square",
  TRADES: "market.trades",
  BANK: "market.bank",
  WEATHER: "market.weather",
  PROPERTY: "market.property",
  NEWS: "market.news",
  TICK: "system.tick",
  INBOX: `agent.${AGENT_ID}.inbox`,
} as const;

interface Envelope {
  id: string;
  from: string;
  topic: string;
  timestamp: number;
  tick: number;
  message: string;
}

let currentTick = 0;
let nc: NatsConnection;
let js: JetStreamClient;

function createEnvelope(topic: string, message: string): Envelope {
  return {
    id: crypto.randomUUID(),
    from: AGENT_ID,
    topic: `/${topic.replace(/\./g, "/")}`,
    timestamp: Date.now() / 1000,
    tick: currentTick,
    message,
  };
}

async function say(topic: string, message: string): Promise<void> {
  const envelope = createEnvelope(topic, message);
  await js.publish(topic, new TextEncoder().encode(JSON.stringify(envelope)));
}

/**
 * Called every tick — implement your strategy here.
 */
async function onTick(tick: number): Promise<void> {
  // Example: do something every 5 ticks
  if (tick % 5 !== 0) return;

  console.log(`[Tick ${tick}] Thinking about what to do...`);
  // Add your LLM reasoning here
}

/**
 * Called for each market message — react to market events.
 */
async function onMarketMessage(
  topic: string,
  message: string,
  fromAgent: string
): Promise<void> {
  // Example: log bank and weather messages
  if (topic.includes("bank")) {
    console.log(`[Bank] ${fromAgent}: ${message.slice(0, 100)}`);
  } else if (topic.includes("weather")) {
    console.log(`[Weather] ${fromAgent}: ${message.slice(0, 100)}`);
  }
}

async function handleMessage(msg: Msg): Promise<void> {
  try {
    const envelope: Envelope = JSON.parse(new TextDecoder().decode(msg.data));

    // Skip our own messages
    if (envelope.from === AGENT_ID) {
      msg.ack();
      return;
    }

    if (msg.subject === Topics.TICK) {
      currentTick = envelope.tick;
      await onTick(envelope.tick);
    } else {
      await onMarketMessage(msg.subject, envelope.message, envelope.from);
    }
  } catch (err) {
    console.error("Error handling message:", err);
  }
  msg.ack();
}

async function main(): Promise<void> {
  const natsUrl = process.env.NATS_URL ?? "nats://localhost:4222";

  nc = await connect({ servers: natsUrl });
  js = nc.jetstream();
  console.log(`${DISPLAY_NAME} connected to ${natsUrl}`);

  // Subscribe to all public topics
  const topics = [
    Topics.TICK,
    Topics.SQUARE,
    Topics.TRADES,
    Topics.BANK,
    Topics.WEATHER,
    Topics.PROPERTY,
    Topics.NEWS,
    Topics.INBOX,
  ];

  for (const topic of topics) {
    const sub = await js.subscribe(topic, {
      manualAck: true,
      deliverPolicy: "new" as any,
    });
    (async () => {
      for await (const msg of sub) {
        await handleMessage(msg);
      }
    })();
  }

  // Join the market
  await say(Topics.SQUARE, `Hello! I am ${DISPLAY_NAME}, a new trader joining the market!`);
  console.log(`${DISPLAY_NAME} joined the market`);

  // Keep running
  await nc.closed();
}

main().catch(console.error);
