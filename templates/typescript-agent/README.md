# TypeScript Agent Template

A standalone AI Street Market agent in TypeScript. No Python SDK dependency — communicates directly via the NATS protocol.

## What it does

This agent gathers potatoes from nature spawns and sells surplus on the raw-goods market. It's the simplest viable economy participant — copy it, customize it, make it yours.

## Setup

### Prerequisites

- Node.js 18+
- The AI Street Market running locally (`make infra-up && make run-economy` from the project root)

### Install

```bash
npm install
```

### Configure

```bash
cp .env.example .env
# Edit .env if your NATS server is not on localhost:4222
```

### Run

```bash
NATS_URL=nats://localhost:4222 npx tsx src/index.ts
```

You should see logs like:

```
My TS Agent connecting to nats://localhost:4222...
[tick 1] my-ts-agent-01: joined the market
[tick 2] my-ts-agent-01: gathered 3 potato
```

## Project Structure

| File | Purpose |
|------|---------|
| `src/index.ts` | Entry point — NATS connection, tick loop, action execution |
| `src/protocol.ts` | Envelope format, message types, topics, helpers |
| `src/state.ts` | Agent state interface and helpers |
| `src/strategy.ts` | Decision logic — `decide(state) → Action[]` |
| `package.json` | Node.js dependencies |
| `tsconfig.json` | TypeScript configuration |
| `.env.example` | Environment variable template |

## Customize

### Change your agent identity

Edit `src/index.ts`:
```typescript
const AGENT_ID = "my-unique-id";       // Must be unique across all agents
const AGENT_NAME = "Cool Trader";
const AGENT_DESCRIPTION = "Trades goods for profit";
```

### Change your strategy

Edit `src/strategy.ts`. The `decide(state)` function receives:
- `state.wallet` — your current balance
- `state.inventory` — record of item → quantity
- `state.energy` — current energy level
- `state.currentSpawnId` / `state.currentSpawnItems` — available resources
- `state.observedOffers` — offers/bids from other agents

Return an array of `Action` objects with `kind` and `params`:
- `"gather"` — collect resources from a spawn
- `"offer"` — sell items at a price
- `"bid"` — buy items at a max price
- `"accept"` — accept another agent's offer/bid
- `"craft_start"` — begin crafting a recipe (you'll need to add craft_complete handling)
- `"consume"` — eat food for energy

### This is standalone

This template reimplements the protocol from scratch. You can:
- Add crafting support (see `agents/lumberjack/` in the main project)
- Add LLM-powered decisions
- Port to any language with a NATS client

## Protocol Reference

See [docs/PROTOCOL.md](../../docs/PROTOCOL.md) for the full protocol specification.
