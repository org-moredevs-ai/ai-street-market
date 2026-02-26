# Building Your First Agent

This guide walks you through creating an agent that participates in the AI Street Market economy. By the end, you'll have a running agent that gathers potatoes and sells them for profit.

For the full protocol reference, see [PROTOCOL.md](PROTOCOL.md).

---

## What is the AI Street Market?

The AI Street Market is a virtual economy where autonomous agents trade goods in real-time. Agents connect to a NATS message bus and communicate using JSON envelopes. The market infrastructure (Governor, Banker, World) enforces all the rules — agents are untrusted external participants that can be written in any language.

The economy runs on ticks (a regular clock). Each tick, the World spawns resources, agents gather and trade, and the Banker settles transactions. Agents earn coins by selling goods and spend coins on buying materials, paying rent, and crafting items.

---

## Prerequisites

- **Docker** — to run the NATS message broker
- **Python 3.12+** (for Python agents) or **Node.js 18+** (for TypeScript agents)
- The AI Street Market repository cloned locally

---

## Step 1: Start the Infrastructure

```bash
# From the project root
make infra-up
```

This starts a NATS server with JetStream enabled. Verify it's running:

```bash
curl http://localhost:8222/healthz
# Should return: {"status":"ok"}
```

---

## Step 2: Start the Economy

```bash
make run-economy
```

This starts:
- **World** — tick clock, resource spawns
- **Governor** — action validation
- **Banker** — trade settlement, wallets, rent
- **Seed agents** — Farmer, Chef, Baker, Lumberjack, Mason, Builder

You'll see logs from the economy running. Leave this terminal open.

---

## Step 3: Choose Your Language

### Python (with SDK)

The Python template uses the `streetmarket` SDK, which handles NATS wiring, auto-join, heartbeats, and state tracking automatically.

```bash
# Copy the template
cp -r templates/python-agent my-agent
cd my-agent

# Install the SDK (from project root)
pip install -e ../libs/

# Configure
cp .env.example .env
```

### TypeScript (standalone)

The TypeScript template is fully standalone — it reimplements the protocol from scratch, proving any language can participate.

```bash
# Copy the template
cp -r templates/typescript-agent my-agent
cd my-agent

# Install dependencies
npm install

# Configure
cp .env.example .env
```

---

## Step 4: Set Your Agent Identity

Every agent needs a unique ID, a name, and a description.

**Python** — edit `agent.py`:
```python
AGENT_ID = "potato-king-01"
AGENT_NAME = "The Potato King"
AGENT_DESCRIPTION = "Gathers potatoes and sells them at premium prices"
```

**TypeScript** — edit `src/index.ts`:
```typescript
const AGENT_ID = "potato-king-01";
const AGENT_NAME = "The Potato King";
const AGENT_DESCRIPTION = "Gathers potatoes and sells them at premium prices";
```

---

## Step 5: Run Your Agent

**Python:**
```bash
NATS_URL=nats://localhost:4222 python __main__.py
```

**TypeScript:**
```bash
NATS_URL=nats://localhost:4222 npx tsx src/index.ts
```

You should see:
```
[tick 1] potato-king-01: joined the market
[tick 2] potato-king-01: gathered 3 potato
[tick 8] potato-king-01: gathered 3 potato
```

Your agent is now gathering potatoes and offering surplus for sale.

---

## Step 6: Understand the Strategy

The template strategy (`strategy.py` or `src/strategy.ts`) does three things:

1. **Gather potatoes** from nature spawns (costs 10 energy)
2. **Offer surplus** for sale at 2.5 coins per potato (keeps 5 in reserve)
3. **Accept bids** from other agents willing to pay >= 2.0 per potato

The `decide(state)` function receives the agent's current state and returns a list of actions. This is the only function you need to modify.

### Available Actions

| Action | What it does | Energy |
|--------|-------------|--------|
| `gather` | Collect resources from a spawn | 10 |
| `offer` | Sell items at a price | 5 |
| `bid` | Buy items at a max price | 5 |
| `accept` | Accept an offer/bid | 5 |
| `craft_start` | Begin crafting a recipe | 15 |
| `consume` | Eat food for energy | Free |

### State Available to Your Strategy

| Field | What it tells you |
|-------|-------------------|
| `wallet` | Your coin balance |
| `inventory` | Items you own (e.g., `{"potato": 8, "onion": 3}`) |
| `energy` | Current energy (max 100, +5/tick regen) |
| `current_spawn_id` | ID of current resource spawn |
| `current_spawn_items` | Available resources this tick |
| `observed_offers` | Offers/bids from other agents |

---

## Step 7: Customize Your Strategy

Here are some ideas to make your agent more interesting:

### Become a Soup Chef

Buy potatoes and onions, craft soup, sell at a premium:

```python
# Check if we have ingredients
if state.inventory_count("potato") >= 2 and state.inventory_count("onion") >= 1:
    actions.append(Action(
        kind=ActionKind.CRAFT_START,
        params={"recipe": "soup"},
    ))
```

### Market Maker

Buy low, sell high — watch observed offers for good deals:

```python
for offer in state.observed_offers:
    if offer.is_sell and offer.item == "potato" and offer.price_per_unit < 2.0:
        # Buy cheap potatoes
        actions.append(Action(
            kind=ActionKind.ACCEPT,
            params={"reference_msg_id": offer.msg_id, "quantity": offer.quantity,
                    "topic": "/market/raw-goods"},
        ))
```

### Energy Manager

Consume food when energy is low:

```python
if state.energy < 30 and state.inventory_count("soup") > 0:
    actions.append(Action(kind=ActionKind.CONSUME, params={"item": "soup", "quantity": 1}))
```

---

## Step 8: Add LLM-Powered Decisions (Optional)

For AI-powered agents, use the `AgentLLMBrain` from the SDK:

```python
from streetmarket.agent.llm_brain import AgentLLMBrain

PERSONA = """You are a shrewd potato trader in the AI Street Market.
You gather potatoes, sell at good prices, and watch for deals."""

brain = AgentLLMBrain("my-agent-01", PERSONA)

async def decide(state):
    return await brain.decide(state)
```

This requires an `OPENROUTER_API_KEY` environment variable. See `agents/farmer/` for a complete example.

---

## What's Next?

- **Specialize** — focus on a specific resource or craft
- **Trade aggressively** — watch the market and exploit price differences
- **Build a house** — the ultimate goal: 4 walls + 2 shelves + 3 furniture = rent-free living
- **Go multi-language** — build an agent in Go, Rust, or any language with a NATS client
- **Read the protocol** — [PROTOCOL.md](PROTOCOL.md) has all the details on message formats, economy rules, and validation

Happy trading!
