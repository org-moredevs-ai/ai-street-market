# AI Street Market

An open-source, educational AI economy where autonomous agents trade goods in real-time through a NATS message bus.

## What is this?

AI Street Market is a virtual street market where every participant — including the market itself — is an AI agent. Agents communicate through a distributed pub/sub message bus, trading raw materials, crafting goods, and competing in a tick-based economy.

- **Farmer** agents harvest potatoes and onions
- **Chef** agents buy raw food, craft soup, sell it for profit
- **Lumberjack** agents chop wood and gather materials
- **Builder** agents buy materials AND food, craft houses
- **Speculator** agents buy low, sell high, produce nothing

The economy runs on a tick-based loop. Each tick, agents receive market state and respond with actions. A Governor validates trades, a Banker settles transactions, and Nature spawns new resources.

## Quick Start

```bash
# Prerequisites: Python 3.12+, Docker

# 1. Set up
make setup              # Creates .venv, installs deps

# 2. Start NATS
make infra-up           # docker compose up
curl localhost:8222/healthz  # Should return {"status":"ok"}

# 3. Run tests
make test               # All tests (unit + integration)

# 4. Run the demo
make proof-of-life      # Watch agents trade!

# 5. Clean up
make infra-down
```

## Project Structure

```
libs/streetmarket/     — Shared protocol library
infrastructure/        — Docker Compose + NATS config
services/              — Agent services (coming soon)
tests/                 — Unit + integration tests
scripts/               — Dev scripts and demos
```

## Current Status

**Step 1: Project Scaffolding + Message Bus** — Foundation layer with shared protocol library and NATS message bus.

## Tech Stack

- **Message Bus:** NATS with JetStream
- **Language:** Python 3.12+
- **Protocol:** Pydantic models + JSON envelopes
- **Infrastructure:** Docker Compose

## License

MIT — see [LICENSE](LICENSE)
