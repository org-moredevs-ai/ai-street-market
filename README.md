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
- **Rent:** 2 coins/tick after a 20-tick grace period. Owning a house exempts an agent from rent.
- **Storage:** Base limit of 50 items + 10 per shelf owned (max 3 shelves = 80 capacity).
- **Bankruptcy:** 5 consecutive ticks at zero wallet + zero inventory = bankrupt and blocked from trading.
- **LLM Nature:** Optional Claude Haiku integration spawns dynamic resources and nature events (droughts, bonanzas).

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
services/              — Market infrastructure (Governor, Banker, World)
infrastructure/        — Docker Compose + NATS config
tests/                 — All tests (631 Python + 22 TypeScript)
scripts/               — Dev scripts, demos, economy runner
sessions/              — Development session journal
references/            — Roadmap and design docs
```

## Current Status

**Step 8: Level 1 Complete** — Full economy with 6 agents, energy system, rent/bankruptcy, storage limits, and optional LLM-powered nature events. 653 total tests.

## Tech Stack

- **Message Bus:** NATS with JetStream
- **Languages:** Python 3.12+, TypeScript (Lumberjack proves language-agnostic protocol)
- **Protocol:** Pydantic models + JSON envelopes
- **AI:** Anthropic Claude (optional, for LLM Nature Intelligence)
- **Infrastructure:** Docker Compose

## License

MIT — see [LICENSE](LICENSE)
