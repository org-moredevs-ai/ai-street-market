# Session: Step 1 — Project Scaffolding + Message Bus

**Date:** 2026-02-19
**Status:** COMPLETED
**Branch:** main
**Commit:** 10e5d7d

## Goal

Bootstrap the AI Street Market monorepo with a shared protocol library (`streetmarket`) and a running NATS message bus that can publish and receive messages.

## What was built

### Phase A: Repository Bootstrap
- `git init` on `main` branch
- `.gitignore` — Python, Docker, .env, IDE, OS files
- `.env.example` — NATS_URL, ANTHROPIC_API_KEY placeholder
- `LICENSE` — MIT
- Root `pyproject.toml` — Python 3.12+, streetmarket as local dep, dev tools (pytest, ruff, mypy)
- `libs/pyproject.toml` — streetmarket package with nats-py + pydantic
- `Makefile` — setup, infra-up/down, test, lint, proof-of-life
- `CLAUDE.md` + `README.md`

### Phase B: NATS Infrastructure
- `infrastructure/nats/nats-server.conf` — ports 4222 (client), 8222 (monitoring), 8080 (WebSocket), JetStream enabled
- `infrastructure/docker-compose.yml` — nats:2.10-alpine with health check and named volume

### Phase C: Shared Library — Models
- `libs/streetmarket/models/topics.py` — Topic constants, `to_nats_subject()` / `from_nats_subject()` conversion (`/` ↔ `.`)
- `libs/streetmarket/models/messages.py` — `MessageType` StrEnum + 11 Pydantic payloads + `PAYLOAD_REGISTRY`
- `libs/streetmarket/models/envelope.py` — `Envelope` with `from_agent` ↔ `"from"` alias

### Phase D: Shared Library — Helpers
- `libs/streetmarket/helpers/factory.py` — `create_message()`, `parse_message()`, `parse_payload()`
- `libs/streetmarket/helpers/validation.py` — `validate_message()`

### Phase E: Unit Tests (42 tests)
- `tests/test_models.py` — model creation, validation constraints, JSON round-trip, topic conversion
- `tests/test_helpers.py` — factory, parse, validation pass/fail

### Phase F: NATS Client
- `libs/streetmarket/client/nats_client.py` — `MarketBusClient` with JetStream stream `STREETMARKET`, publish/subscribe, reconnection, `DeliverPolicy.NEW` for ephemeral subscribers

### Phase G: Integration Tests + Proof of Life (4 tests)
- `tests/conftest.py` — `bus_client` async fixture
- `tests/test_nats_client.py` — connect/disconnect, pub/sub round-trip, multiple messages
- `tests/test_proof_of_life.py` — full offer → bid → accept flow
- `scripts/proof_of_life.py` — standalone demo script

### Phase H: Commit + Push
- All 46 tests passing (42 unit + 4 integration)
- Pushed to `git@github.com:org-moredevs-ai/ai-street-market.git`
- Removed `references/` from repo (gitignored)

## Issues encountered

1. **Root pyproject.toml flat-layout error** — setuptools discovered multiple top-level packages. Fixed by adding `[tool.setuptools] py-modules = []`.
2. **JetStream delivering stale messages in tests** — ephemeral subscribers received historical messages from previous test runs. Fixed by adding `deliver_policy=DeliverPolicy.NEW` for non-durable subscriptions.
3. **GitHub repo didn't exist** — created with `gh repo create` before pushing.

## Key decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Topic paths vs NATS subjects | `/` in app, `.` in NATS | App code matches spec; NATS gets native format |
| Envelope `from` field | `from_agent` in Python, `"from"` in JSON | Python reserved keyword handled via Pydantic alias |
| JetStream from day 1 | Enabled immediately | Free persistence + replay, no rework later |
| DeliverPolicy.NEW for ephemeral | Only new messages delivered | Prevents stale message issues in tests and fresh subscribers |

## How to verify

```bash
make setup && make infra-up && make test && make proof-of-life && make infra-down
```

## Next step

Step 2: Governor Agent — hardcoded Phase 1 rule validation on the bus.
