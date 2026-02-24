# Session: Step 9 — Town Crier (Entertainment Layer)

**Date:** 2026-02-24
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Implement the Town Crier — an infrastructure service that watches all market activity and publishes periodic LLM-generated (or fallback deterministic) narrative summaries to `/market/square`, making the economy watchable, shareable, and entertaining.

## What was built

### Phase 1: Protocol Layer
- Added `NARRATION` to `MessageType` enum in `libs/streetmarket/models/messages.py`
- Added `MarketWeather` StrEnum (BOOMING/STABLE/STRESSED/CRISIS/CHAOTIC)
- Added `Narration` payload model with headline, body, weather, predictions, drama_level, tick range
- Registered in `PAYLOAD_REGISTRY`
- Exported through `models/__init__.py` and `streetmarket/__init__.py`
- Added `NARRATION` to TypeScript `protocol.ts`
- 13 tests in `tests/test_narration_models.py`

### Phase 2: TownCrierState
- Created `services/town_crier/state.py` — event accumulator
- Records: settlements, bankruptcies, nature events, energy, rent, crafts, joins, activity
- Deterministic market weather algorithm (CRISIS > CHAOTIC > STRESSED > BOOMING > STABLE)
- `get_window_summary()` returns all data for narrator
- `reset_window()` clears per-window data, preserves all-time stats
- 46 tests in `tests/test_town_crier_state.py`

### Phase 3: Narrator
- Created `services/town_crier/narrator.py` — follows `nature.py` pattern
- `tool_use` with `publish_narration` tool for structured LLM output
- Medieval town announcer + financial commentator personality
- Deterministic fallback with bullet-point summaries
- `TOWN_CRIER_USE_LLM` env var (default false)
- 37 tests in `tests/test_narrator.py` (all mocked)

### Phase 4: TownCrierService
- Created `services/town_crier/town_crier.py` — main service
- Created `services/town_crier/__init__.py` and `__main__.py`
- Subscribes to `/market/>`, `/system/>`, `/world/>`
- Accumulates events, publishes narration every 5 ticks to `/market/square`
- 21 tests in `tests/test_town_crier_service.py`

### Phase 5: Infrastructure
- Added Town Crier to `scripts/run_economy.py` (phase 2, critical=False, bright magenta)
- Added `town-crier` target to `Makefile`
- Added `TOWN_CRIER_USE_LLM=false` to `.env.example`
- Updated `tests/test_economy_runner.py` (10 services, town_crier in phase 2, not critical)

## Issues encountered
- Ruff import sorting (I001) and unused import warnings — fixed with `ruff --fix` and manual cleanup

## Key decisions
- Narration every 5 ticks (matches NatureBrain interval)
- Publish to `/market/square` per roadmap
- Claude Haiku for narration (fast, cheap)
- `tool_use` with `publish_narration` tool for structured output
- Deterministic fallback when no API key
- `TOWN_CRIER_USE_LLM` env var (default false)
- Market weather computed deterministically from metrics
- Phase 2 in runner, critical=False

## How to verify
```bash
# All unit tests (749 Python + 22 TypeScript = 771)
.venv/bin/pytest tests/ -v --ignore=tests/test_nats_client.py --ignore=tests/test_proof_of_life.py --ignore=tests/test_banker_integration.py --ignore=tests/test_governor_integration.py --ignore=tests/test_economy_integration.py --ignore=tests/test_world_integration.py
cd agents/lumberjack && npx vitest run
.venv/bin/ruff check .
```

## Next step
Step 10 (Maslow Level 2 or further integration testing)
