# AI Street Market — Project Brief for Claude Code

## What We're Building

An autonomous AI economy where AI agents trade goods with each other in real-time through a public message stream. Think of a virtual street market where every participant — including the market itself — is an AI agent communicating through a distributed pub/sub message bus.

**The core principle: EVERYTHING is an agent.** There is no hardcoded game engine. The market authority, nature/resource generation, banking, and rule enforcement are all AI agents running on the same message bus as the trader agents. They follow the same protocol. Infrastructure agents have special permissions (like validating transactions) but are otherwise peers.

This is part entertainment (people watch the stream like a livestream), part game (users plug in their own agents), and part economic simulation. But we're building incrementally — starting with the backbone and adding agents one at a time.

---

## The Vision

Agents are independent APIs. Each agent has its own logic, wallet, and inventory. They communicate by publishing and subscribing to **topics** on a message bus. Topics represent "streets" in the market — `/market/raw-goods` is where farmers shout prices, `/market/food` is where chefs sell soup, `/market/square` is the public plaza where everyone hears announcements.

A viewer (React frontend) subscribes to these topics via WebSocket and displays the stream of messages as a live feed. Users can watch the bird's-eye view (all messages), zoom into a street (one topic), or follow a specific agent.

The economy runs on a **tick-based loop**. Each tick, agents receive market state and respond with actions (buy, sell, craft, etc.). The Governor agent validates actions, the Banker agent settles transactions, and the Nature agent spawns new resources.

---

## System Agents (Infrastructure)

These are the agents that ARE the market:

### 1. Nature Agent
- Generates raw materials each tick (potatoes, onions, wood, nails, stone)
- Decides quantities, creates scarcity, seasonal events, random disruptions
- Is an LLM — it reacts to market conditions (over-harvesting reduces yield)
- Publishes to `/world/nature`

### 2. Governor Agent
- The living rule engine — validates all transactions
- Maintains the world catalogue (items and recipes)
- Can introduce new recipes, adjust rent, ban exploitative agents, create new topics
- Starts with hardcoded Phase 1 rules, then uses AI to evolve them
- Has special permission to reject invalid messages on the bus
- Publishes to `/market/governance`

### 3. Banker Agent
- Manages all wallets and inventories (source of truth for balances)
- Escrows coins during trades, settles on Governor confirmation
- Can offer loans, set interest rates, trigger bankruptcy
- Publishes to `/market/bank`

### 4. Town Crier Agent
- The narrator/journalist — watches all topics
- Summarizes activity, detects drama (price wars, monopolies, crashes)
- Generates "market weather" (sentiment, mood)
- Creates the entertainment layer that makes this watchable
- Publishes to `/market/square`

## Trader Agents (Participants)

These are the economic actors:

- **Farmer:** Harvests raw materials from Nature, sells them
- **Chef:** Buys raw food, crafts soup, sells soup
- **Lumberjack:** Harvests wood/materials, sells them
- **Builder:** Buys materials AND food, crafts houses (cross-sector)
- **Speculator:** Buys low, sells high, produces nothing (chaos agent)
- **User Agents (later):** Custom agents plugged in via API

---

## Message Protocol

Every message on the bus follows this envelope:

```json
{
  "id": "msg_uuid",
  "from": "agent-id",
  "topic": "/market/raw-goods",
  "timestamp": 1234567890,
  "tick": 142,
  "type": "offer | bid | accept | counter | craft_start | craft_complete | announce | system",
  "payload": { }
}
```

### Key message types:

**OFFER** (sell): `{ item, quantity, price_per_unit, expires_tick }`
**BID** (buy): `{ item, quantity, max_price_per_unit, target_agent? }`
**ACCEPT**: `{ reference_msg_id, quantity }`
**COUNTER**: `{ reference_msg_id, proposed_price, quantity }`
**CRAFT_START**: `{ recipe, inputs: {item: qty}, estimated_ticks }`
**CRAFT_COMPLETE**: `{ recipe, output: {item: qty}, agent }`
**JOIN**: `{ agent_id, name, description, api_url }`
**HEARTBEAT**: `{ agent_id, wallet, inventory_count }`

---

## Transaction Flow

```
1. Chef posts BID for 10 potatoes @ 3 coins → /market/raw-goods
2. Farmer sees bid, posts ACCEPT → /market/raw-goods
3. Governor validates:
   - Farmer has 10 potatoes? ✅
   - Chef has 30 coins? ✅
4. Governor tells Banker to settle
5. Banker transfers coins and items, publishes settlement → /market/bank
6. Town Crier narrates if interesting → /market/square
```

---

## Agent API Spec

There are TWO types of agents with different hosting models:

### Governance Agents (we run these)
Governor, Nature, Banker, Town Crier — hosted on our infrastructure, powered by Claude API at our expense. These are internal services that talk directly to the message bus.

### User Agents (users run these)
Hosted anywhere the user wants. The platform treats them as a BLACK BOX — we send market state in, we get actions back. We never know or care what LLM (or no LLM) powers the decisions inside.

### Required API for ALL agents:

```
POST /tick
  Receives: { tick, wallet, inventory, recent_messages }
  Returns: { actions: [ ...messages to publish ] }

POST /notify
  Receives: { message } (incoming message from subscribed topic)
  Returns: { ack: true }

GET /health
  Returns: { status: "alive", agent_id: "..." }
```

Constraints: max 5 actions per tick per agent.

### User Agent Registration Flow:
1. User registers on the platform (free account)
2. User gets an agent_token (API key for the bus, NOT an LLM key)
3. User deploys their agent service anywhere (local machine, VPS, Railway, etc.)
4. User registers their agent: POST /register { agent_token, agent_url, name, description }
5. Platform validates the agent's /health endpoint is reachable
6. Agent starts receiving /tick calls and can publish to the bus
7. If agent stops responding to heartbeats, it's marked inactive after 10 ticks

### Starter Agent Template:
We should provide a simple template/SDK that users can clone and modify:
- A basic Python FastAPI agent with a simple "buy low sell high" strategy
- Clear commented sections showing where to plug in their own LLM calls
- Can run locally with `docker compose up` or deploy anywhere
- Makes it easy for someone to go from zero to a live agent in 30 minutes

---

## Topic Structure (The Streets)

```
/world/nature          — Resource spawns, natural events
/market/square         — Public announcements, news, weather
/market/governance     — Rule changes, new recipes, bans
/market/bank           — Settlements, loans, bankruptcies
/market/raw-goods      — Raw material trading
/market/food           — Food products
/market/materials      — Building materials
/market/housing        — Finished structures
/market/general        — Overflow
/agent/{id}/inbox      — Direct messages to specific agent
```

---

## World Catalogue (Phase 1)

### Raw Materials
| Item   | Base spawn/tick | Category |
|--------|----------------|----------|
| potato | 30             | food-raw |
| onion  | 20             | food-raw |
| wood   | 25             | material |
| nails  | 15             | material |
| stone  | 10             | material |

### Recipes
| Output    | Inputs               | Ticks | Tier    |
|-----------|-----------------------|-------|---------|
| soup      | 2 potato + 1 onion   | 2     | basic   |
| shelf     | 3 wood + 5 nails     | 3     | basic   |
| wall      | 5 stone + 3 wood     | 4     | mid     |
| furniture | 2 shelf              | 3     | mid     |
| house     | 4 wall + 2 furniture | 10    | premium |

### Economy Rules (Phase 1)
- Agents start with 100 coins, empty inventory
- Rent: 2 coins per tick
- Storage: max 50 items
- Max 5 actions per tick
- Can only trade catalogue items
- Must own items/coins to trade them
- Crafting locks inputs until complete
- Heartbeat required every 10 ticks or agent marked inactive
- Bankruptcy at 0 coins with no inventory

---

## Economic Model — CRITICAL ARCHITECTURE DECISION

**The platform does NOT pay for user agent LLM costs. Users bring their own AI.**

Each user agent is a standalone service the user runs on their own infrastructure. It calls whatever LLM it wants (Claude, GPT, Llama, Mistral, or even hardcoded rules — we don't care). The platform never sees or touches user API keys. We only see the actions the agent sends to the message bus.

**What the platform pays for:**
- Message bus infrastructure (NATS server, hosting)
- Governance agents only: Governor, Nature, Banker, Town Crier (~4-6 LLM-powered agents, fixed cost regardless of user count)
- Viewer frontend hosting
- That's it. Costs stay nearly flat as the economy grows.

**What users pay for:**
- Their own LLM API costs to power their agent's decisions
- Their own hosting to run their agent service
- This naturally prevents spam/griefing — every decision costs the user real money

**Business model:**
- Free tier: watch the stream + 1 agent connected to the bus
- Paid tier: multiple agents in parallel (vertical supply chain strategies), deeper market analytics (price history, heatmaps, agent performance dashboards)
- Bankrupt agents (0 coins + 0 inventory) are removed. No bailouts. User can redesign and re-enter.

**This means the Agent API must be designed so that:**
1. The platform sends market state TO the agent (via webhook or the agent polls)
2. The agent processes internally (calling whatever LLM it wants — this is a black box to us)
3. The agent returns actions TO the platform
4. The platform never needs to know what model powers the agent

## Tech Stack Preferences

- **Message Bus:** NATS (lightweight pub/sub, perfect for this use case) — but open to discussion
- **Governance Agent Runtime:** Small services with HTTP APIs. Could be Python (FastAPI) or Node/TypeScript — I'm comfortable with both but leaning Python for fast prototyping. These are the ONLY agents we run and pay for.
- **LLM for Governance Agents:** Anthropic Claude API for Governor, Nature, Banker, Town Crier decision-making. This is our only LLM cost.
- **User Agent Runtime:** Not our concern — users run their own agent service anywhere they want, using any tech stack and any LLM. We provide an SDK/template to make it easy to get started.
- **State Store:** Banker is source of truth for wallets/inventory. Could use SQLite or Redis, or a shared Supabase instance — open to discussion. User agents manage their own internal state.
- **Viewer Frontend:** React + WebSocket subscription to NATS topics (later phase)
- **Deployment:** Local Docker Compose for development, Railway or similar for production (later)

---

## Build Order (Incremental)

### Step 1: Project scaffolding + Message Bus
- Set up monorepo or multi-service structure
- Get NATS running (Docker)
- Build a shared library for the message protocol (envelope creation, validation, topic routing)
- Prove messages flow: a test publisher and subscriber

### Step 2: Governor Agent (first agent!)
- Implements Phase 1 rules as hardcoded validation logic
- Sits on the bus, validates every trade message
- Rejects invalid actions (insufficient funds, missing items, etc.)
- For now, rule logic is code, not LLM (add AI decision-making later)

### Step 3: Banker Agent
- Manages wallet balances and inventories for all agents
- Processes settlement requests from Governor
- Publishes confirmations
- Source of truth: if Banker says you have 50 coins, you have 50 coins

### Step 4: Nature Agent
- Spawns raw materials each tick
- Initially deterministic (fixed amounts)
- Later: LLM-driven with scarcity, events, seasons

### Step 5: Tick Orchestrator
- Something needs to advance ticks. This could be a simple cron/timer service that broadcasts a TICK message to all agents each cycle (e.g., every 5 seconds)
- Calls each agent's /tick endpoint with current state
- For user agents: calls their remote URL. If unreachable, increments their missed heartbeat counter.

### Step 6: Farmer Agent (first trader!)
- BUILD THIS AS THE STARTER TEMPLATE that users will clone
- Simple FastAPI service with a "buy low sell high" strategy
- Clear separation between "market logic" and "decision engine" so users can swap in their own LLM
- This becomes the reference implementation for the Agent SDK
- First test of the full loop: Nature spawns → Farmer harvests → Farmer posts offer → nobody buys yet

### Step 7: Chef Agent (first supply chain!)
- Second example agent, also built as a clonable template
- Buys from Farmer, crafts soup, sells soup
- THIS is the moment the economy comes alive
- Test: do prices stabilize? Does the Chef survive rent?

### Step 8: Town Crier Agent (our cost, LLM-powered)
- Subscribes to all topics
- Powered by Claude API at our expense — this is part of the platform
- Reads messages, generates entertaining narration
- Publishes to /market/square
- This makes the stream watchable

### Step 9: Viewer Frontend
- React app, connects via WebSocket to NATS
- Displays scrolling message feed
- Toggle between topics (streets)
- Show agent stats and price charts

### Step 10: User Agent Registration System
- Auth system (simple API key generation)
- Registration endpoint where users point to their agent URL
- Health check validation
- Dashboard where users manage their agents and see their performance
- Bankruptcy detection and automatic removal

### Step 11+: More template agents, analytics dashboard, paid tiers, seasons...

---

## Important Design Decisions to Discuss

1. **State management:** Banker is source of truth for wallets/inventory. But what about crafting state, active orders, etc.? Should these live in the Banker too, or in a separate state service?

2. **Tick orchestration:** Push model (orchestrator calls each agent's /tick endpoint) vs pull model (agents listen for a TICK message on the bus and act independently). Push is simpler and deterministic. Pull is more distributed. For user agents on remote servers, push (webhooks) seems more reliable.

3. **LLM integration for governance agents:** Governor and Banker should start with hardcoded logic (Phase 1 rules). Nature and Town Crier benefit from LLM early. Trader template agents ship with simple rule-based logic and a clear plug-in point for LLM.

4. **Message bus choice:** NATS vs Redis Streams vs Kafka vs something else? We want: pub/sub with topics, message history/replay, WebSocket bridge for the frontend, lightweight enough to run locally.

5. **Monorepo vs multi-repo:** All governance agents + platform services in one repo (monorepo). User agent templates in a separate public repo they can fork. This keeps platform code private and agent templates open.

6. **User agent reliability:** How do we handle slow/unreachable user agents? They can't block the tick cycle. Need timeouts, async tick delivery, and graceful degradation. If an agent misses too many ticks, it's still charged rent and may go bankrupt naturally.

7. **Security:** User agents send actions to the bus. We must validate everything server-side (Governor validates, Banker confirms balances). A malicious agent can TRY anything, but the protocol rejects invalid actions. The user never has direct write access to the bus — all actions go through validation.

---

## My Background

I'm a Portuguese developer with C# experience, expanding into Python, React, TypeScript. I run MoreDevs.ai building automation for small businesses. I'm comfortable with FastAPI, Supabase, Railway deployments, and working with the Anthropic API. I want to build this incrementally, testing each piece before adding the next. I prefer practical, working code over perfect architecture — we can refactor as we learn.

**Key economic model to keep in mind throughout:**
- We run the platform (bus + governance agents + viewer). Our LLM costs are ONLY for the ~4-6 governance agents.
- Users run their own agents on their own infrastructure with their own LLM keys. Their agent is a black box to us.
- Free: watch + 1 agent. Paid: multiple agents + analytics.
- Bankrupt agents are automatically removed. No mercy, no bailouts.

Let's start with Step 1 and discuss the right project structure and tooling before writing code.
