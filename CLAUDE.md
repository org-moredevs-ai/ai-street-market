# AI Street Market

## Overview
An open-source AI economy where autonomous agents trade goods in real-time through a NATS message bus. Agents communicate via pub/sub topics, trading raw materials, crafting goods, and competing in a tick-based economy.

## Architecture
- **Message Bus:** NATS with JetStream (persistence + replay)
- **Shared Library:** `streetmarket` package in `libs/` — models, helpers, NATS client, Agent SDK
- **Services:** Market infrastructure in `services/` — Governor (validator), Banker (settlements), World (nature/ticks)
- **Agents:** Trading participants in `agents/` — Farmer, Chef, Baker, Mason, Builder (Python), Lumberjack (TypeScript)
- **Infrastructure:** Docker Compose for NATS
- **Strategy Pattern:** Each agent uses `decide(state) → list[Action]` pure functions, fully testable without NATS

## AI-Mandatory Rule (NON-NEGOTIABLE)
This is the AI Street Market. Every agent and every content-generating service
MUST use LLM (via OpenRouter) for decision-making and content generation. There is NO
hardcoded-only mode. `OPENROUTER_API_KEY` is required to run the economy.
Hardcoded strategies (`decide_hardcoded`) exist ONLY as test fixtures, never as runtime fallbacks.
When adding new agents or services, LLM integration is mandatory from day one.
The test suite enforces this — see `tests/test_ai_guardrails.py`.

## Agent Isolation Principle (ARCHITECTURAL BOUNDARY)
Agents are EXTERNAL participants. The `agents/` directory contains seed/example
agents that bootstrap the economy and serve as reference implementations.
They are NOT part of the market infrastructure.

Anyone can build an agent in ANY language. Agents only need:
1. A NATS connection
2. Knowledge of the protocol (see `docs/PROTOCOL.md`)

The market infrastructure (Governor, Banker, World, Town Crier) enforces all rules.
Agents cannot cheat — they are untrusted by design.

See `docs/BUILDING_AN_AGENT.md` for the getting started guide.
See `templates/` for minimal starter agents.

## Key Conventions
- Python 3.12+ required
- All services import `from streetmarket import ...`
- Topic paths use `/` in app code (e.g., `/market/raw-goods`), converted to NATS `.` subjects internally
- Envelope `from` field → `from_agent` in Python (reserved keyword), `"from"` in JSON via Pydantic alias
- JetStream stream `STREETMARKET` captures `world.>`, `market.>`, `agent.>`, `system.>`

## Development
```bash
make setup          # Create venv + install deps
make infra-up       # Start NATS (Docker)
make infra-down     # Stop NATS
make test           # Run all tests
make lint           # Ruff + mypy
make proof-of-life  # Run demo script
make run-economy    # Run full economy (all services + agents)

# Individual services/agents
make governor       # Validation service
make banker         # Settlement service
make world          # Nature/tick engine
make farmer         # Potato/onion gatherer
make chef           # Soup crafter
make baker          # Bread crafter
make lumberjack     # Wood/nails gatherer (TypeScript)
make mason          # Stone gatherer, wall crafter
make builder        # House crafter
```

## Testing
- Unit tests (`test_models.py`, `test_helpers.py`): no NATS needed
- Integration tests (`test_nats_client.py`, `test_proof_of_life.py`): require `make infra-up`
- Use `pytest-asyncio` with `asyncio_mode = "auto"`

## Message Protocol
Every message uses an `Envelope` with: id, from, topic, timestamp, tick, type, payload.

Message types:
- **Trading:** offer, bid, accept, counter, settlement
- **Crafting:** craft_start, craft_complete
- **Resources:** spawn, gather, gather_result, consume, consume_result
- **Energy:** energy_update
- **Economy:** rent_due, bankruptcy, nature_event
- **System:** join, heartbeat, tick, validation_result

## Economy Mechanics
- **Energy:** Actions cost energy (gather=10, craft=15, trade=5). Regenerates 5/tick. Food restores energy (soup=30, bread=20).
- **Rent:** 0.5 coins/tick after 50-tick grace period. House ownership exempts agents.
- **Storage:** Base limit 50 items + 10 per shelf owned (max 3 shelves = 80).
- **Bankruptcy:** 15 consecutive ticks at zero wallet = bankrupt (blocked from trading). Inventory doesn't prevent bankruptcy — assets are liquidated via confiscation.
- **LLM Nature:** LLM-powered nature intelligence for dynamic resource spawns and nature events.

## Project Structure
```
libs/streetmarket/     — Shared protocol library (models, helpers, client, Agent SDK)
  models/              — Envelope, messages, catalogue, energy, rent, topics
  agent/               — TradingAgent base class, AgentState, Action
  helpers/             — Factory, validation, topic mapping
  client/              — NATS client wrapper
agents/                — Trading agents (external participants)
  farmer/              — Gathers potato + onion, sells raw goods
  chef/                — Buys potato + onion, crafts soup, sells food
  baker/               — Buys potato, crafts bread, sells food
  lumberjack/          — (TypeScript) Gathers wood + nails, crafts shelf
  mason/               — Gathers stone, buys wood, crafts wall
  builder/             — Buys wall + shelf + furniture, crafts house
services/              — Market infrastructure
  governor/            — Validates all actions (business rules, energy checks)
  banker/              — Settles trades, manages wallets/inventory, rent, bankruptcy
  world/               — Tick engine, resource spawns, energy authority, LLM nature
infrastructure/        — Docker Compose + NATS config
templates/             — Agent starter templates (Python + TypeScript)
docs/                  — Protocol spec, getting started guide
tests/                 — All tests (894 Python + 50 TypeScript)
scripts/               — Dev scripts, demos, economy runner
sessions/              — Development session journal (see below)
references/            — Roadmap and design docs
```

## Session Journal (MANDATORY)

The `sessions/` folder is the project's development memory. It ensures continuity if a Claude session crashes, times out, or a new session picks up where the last left off.

### Rules — follow these ALWAYS:

1. **Before starting work:** Read the latest session file in `sessions/` to understand current state, what was done last, and what the next step is.
2. **At the start of a new task:** Create a new session file following the naming convention below. Fill in the header fields and the **Goal** section immediately, before writing any code.
3. **During development:** Update the session file as you go — log issues encountered, decisions made, and progress through phases. Do this periodically, not just at the end.
4. **After completing work:** Update the session file with final status, commits, verification steps, and what the next step should be.
5. **Never skip this.** Even for small fixes. A 10-line session file for a bugfix is better than nothing.

### File naming convention
```
sessions/YYYY-MM-DD-<short-description>.md
```
Examples:
- `2026-02-19-step1-scaffolding-message-bus.md`
- `2026-02-20-step2-governor-agent.md`
- `2026-02-20-fix-jetstream-delivery-policy.md`

### Session file template
```markdown
# Session: <Title>

**Date:** YYYY-MM-DD
**Status:** IN_PROGRESS | COMPLETED | BLOCKED
**Branch:** main | feature/xxx
**Commit:** (fill when done)

## Goal
What this session aims to accomplish.

## What was built
Describe what was implemented, organized by phase or component.

## Issues encountered
Problems hit and how they were solved. This is critical for future sessions.

## Key decisions
Important choices made and why.

## How to verify
Commands to confirm everything works.

## Next step
What should be done next. This is what the next session picks up.
```

### How to resume from a crashed session
1. List files in `sessions/` — find the latest one
2. Check its **Status** — if `IN_PROGRESS`, that's where we stopped
3. Read **What was built** to know what's already done
4. Read **Issues encountered** to avoid repeating mistakes
5. Read **Next step** or the incomplete phases to know what to do
6. Create a new session file continuing from there
