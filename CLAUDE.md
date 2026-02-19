# AI Street Market

## Overview
An open-source AI economy where autonomous agents trade goods in real-time through a NATS message bus. Agents communicate via pub/sub topics, trading raw materials, crafting goods, and competing in a tick-based economy.

## Architecture
- **Message Bus:** NATS with JetStream (persistence + replay)
- **Shared Library:** `streetmarket` package in `libs/` — models, helpers, NATS client
- **Services:** Each agent is an independent service in `services/`
- **Infrastructure:** Docker Compose for NATS

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
```

## Testing
- Unit tests (`test_models.py`, `test_helpers.py`): no NATS needed
- Integration tests (`test_nats_client.py`, `test_proof_of_life.py`): require `make infra-up`
- Use `pytest-asyncio` with `asyncio_mode = "auto"`

## Message Protocol
Every message uses an `Envelope` with: id, from, topic, timestamp, tick, type, payload.
Message types: offer, bid, accept, counter, craft_start, craft_complete, join, heartbeat, tick, settlement, validation_result.

## Project Structure
```
libs/streetmarket/     — Shared protocol library (models, helpers, client)
infrastructure/        — Docker Compose + NATS config
services/              — Agent services (future)
tests/                 — All tests
scripts/               — Dev scripts and demos
sessions/              — Development session journal (see below)
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
