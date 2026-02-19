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
references/            — Project briefs and specs
```
