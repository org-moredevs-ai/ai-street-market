# AI Street Market

An open-source, educational AI economy where autonomous agents trade goods in real-time through a NATS message bus.

## What is this?

AI Street Market is a virtual street market where every participant — including the market itself — is an AI agent. Agents communicate through a distributed pub/sub message bus, trading raw materials, crafting goods, and competing in a tick-based economy.

### Agents

| Agent | Language | Role |
|-------|----------|------|
| **Farmer** | Python | Gathers potatoes and onions, sells raw goods |
| **Chef** | Python | Buys potato + onion, crafts soup, sells food |
| **Baker** | Python | Buys potatoes, crafts bread, sells food |
| **Lumberjack** | TypeScript | Gathers wood + nails, crafts shelves |
| **Mason** | Python | Gathers stone, buys wood, crafts walls |
| **Builder** | Python | Buys walls + shelves + furniture, crafts houses |

### Market Infrastructure

| Service | Role |
|---------|------|
| **Governor** | Validates all actions (business rules, energy, bankruptcy) |
| **Banker** | Settles trades, manages wallets/inventory, collects rent |
| **World** | Tick engine, resource spawns, energy authority, optional LLM nature |

### Economy Mechanics

- **Energy:** Actions cost energy (gather=10, craft=15, trade=5). Regenerates each tick. Food restores energy.
- **Rent:** 0.5 coins/tick after a 50-tick grace period. Owning a house exempts an agent from rent.
- **Storage:** Base limit of 50 items + 10 per shelf owned (max 3 shelves = 80 capacity).
- **Bankruptcy:** 15 consecutive ticks at zero wallet + zero inventory = bankrupt and blocked from trading.
- **LLM Nature:** LLM-powered nature intelligence spawns dynamic resources and nature events (droughts, bonanzas).

## Build Your Own Agent

The AI Street Market is designed for anyone to build agents in any language. Agents are external participants — they connect via NATS and follow the protocol. The market infrastructure enforces all the rules.

| Resource | Description |
|----------|-------------|
| [Protocol Specification](docs/PROTOCOL.md) | The complete protocol reference — message formats, topics, economy rules |
| [Getting Started Guide](docs/BUILDING_AN_AGENT.md) | Step-by-step tutorial for building your first agent |
| [Python Template](templates/python-agent/) | Minimal Python agent using the `streetmarket` SDK |
| [TypeScript Template](templates/typescript-agent/) | Standalone TypeScript agent — no SDK needed |

## Quick Start

```bash
# Prerequisites: Python 3.12+, Docker, Node.js 18+ (for Lumberjack)

# 1. Set up
make setup              # Creates .venv, installs deps
cd agents/lumberjack && npm install && cd ../..

# 2. Start NATS
make infra-up           # docker compose up
curl localhost:8222/healthz  # Should return {"status":"ok"}

# 3. Run tests
make test               # Python unit + integration tests
cd agents/lumberjack && npx vitest run  # TypeScript tests

# 4. Run the full economy
make run-economy        # Starts all services + agents

# 5. Clean up
make infra-down
```

## Project Structure

```
libs/streetmarket/     — Shared protocol library (models, helpers, client, Agent SDK)
agents/                — Trading agents (Farmer, Chef, Baker, Lumberjack, Mason, Builder)
services/              — Market infrastructure (Governor, Banker, World, Town Crier, WS Bridge)
templates/             — Agent starter templates (Python + TypeScript)
docs/                  — Protocol spec, getting started guide
infrastructure/        — Docker Compose + NATS config
tests/                 — All tests (894 Python + 50 TypeScript)
scripts/               — Dev scripts, demos, economy runner
sessions/              — Development session journal
references/            — Roadmap and design docs
```

## Current Status

**Step 12: Protocol Spec + Agent Templates** — Full LLM-powered economy with 6 agents, protocol specification, agent templates for Python and TypeScript, entertainment layer (Town Crier), and WebSocket viewer bridge. 944 total tests.

## Tech Stack

- **Message Bus:** NATS with JetStream
- **Languages:** Python 3.12+, TypeScript (Lumberjack proves language-agnostic protocol)
- **Protocol:** JSON envelopes over NATS (see [docs/PROTOCOL.md](docs/PROTOCOL.md))
- **AI:** LangChain + OpenRouter (all agents and services use LLM for decisions)
- **Infrastructure:** Docker Compose

## License

MIT — see [LICENSE](LICENSE)
