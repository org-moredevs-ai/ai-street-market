# Session: Step 6 — Economy Runner + Maslow Roadmap

**Date:** 2026-02-22
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Two parallel deliverables:
- **6A: Economy Runner** — single `make run-economy` command that starts NATS + all services + all agents, streams color-coded logs, shuts down cleanly on Ctrl+C
- **6B: Maslow Roadmap** — design document mapping the economy to Maslow's hierarchy of needs, guiding future agent and item development

## What was built

### Phase 1: Economy Runner script
- `scripts/run_economy.py` — ~250 lines
  - `ServiceDefinition` frozen dataclass (name, label, command, color, phase, critical)
  - `ManagedProcess` wraps asyncio subprocess with color-prefixed log streaming
  - `EconomyRunner` orchestrates phased startup, crash watching, graceful shutdown
  - NATS auto-start via docker compose if not running, health check via port 8222
  - Phased startup: NATS → world+governor+banker → farmer+chef+lumberjack
  - Color-coded output with 10-char padded labels
  - Ctrl+C → SIGTERM (reverse order) → 5s grace → SIGKILL

### Phase 2: Runner tests
- `tests/test_economy_runner.py` — unit tests for service definitions, formatting, phases

### Phase 3: Makefile target
- Added `run-economy` target to Makefile

### Phase 4: Maslow roadmap document
- `docs/maslow-roadmap.md` — full hierarchy mapping, energy system design, catalogue analysis, level-by-level expansion plan

### Phase 5: Finalize
- Lint + tests pass
- Session journal updated

## Issues encountered
- Import ordering: ruff flagged unsorted imports in test file — fixed with `ruff --fix`
- Pre-existing mypy errors in `libs/streetmarket/` (20 errors across 3 files from Steps 2-5) — not introduced by Step 6

## Key decisions
- Python asyncio for runner — matches project stack, no external deps
- NATS left running on exit — `make infra-down` already exists for cleanup
- Critical service (world/governor/banker) crash → shutdown all; agent crash → non-fatal
- Energy system enforcement is server-side (World Engine + Governor) — agents can't bypass it

## How to verify
```bash
# Unit tests (no NATS)
.venv/bin/pytest tests/test_economy_runner.py -v

# Full economy run
make run-economy
# → NATS starts, services start, agents start, logs stream
# → Ctrl+C → graceful shutdown

# Lint
make lint

# All tests still pass
make infra-up && make test
```

## Next step
Step 7 — Energy System + Complete Level 1 (World Engine energy tracking, CONSUME message, Mason+Builder agents)
