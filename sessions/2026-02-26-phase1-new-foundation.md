# Session: Phase 1 — New Foundation

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Build the deterministic infrastructure layer for v2:
- Policy engine (load YAML, parse into structures)
- Ledger (interface-based, in-memory. Wallets, inventory, transactions)
- Agent registry (onboarding, profiles, state management)
- World state store (fields, buildings, weather, resources)
- Season manager (UTC dates -> ticks, phase lifecycle)
- Ranking engine (per-season + overall)
- Tick clock (UTC-aware, configurable interval)
- NATS NKey auth + topic permissions
- Tests for all components

## What was built

### Policy Engine (`libs/streetmarket/policy/engine.py`)
- `PolicyEngine` loads YAML world + season configs
- `SeasonConfig` dataclass with computed `total_ticks`, `closing_tick`, `duration_seconds`
- `WorldPolicy` with `raw_text` for LLM prompt injection
- Support for regions, crops, resources, weather, crafting, energy, economy
- Full parsing of `season-1.yaml` and `earth-medieval-temperate.yaml`

### Ledger (`libs/streetmarket/ledger/`)
- `LedgerInterface` Protocol (runtime_checkable) — future blockchain swap
- `InMemoryLedger` with Decimal arithmetic for wallets
- FIFO batch tracking for inventory (`InventoryBatch`)
- Transfer, credit/debit, add/remove items
- Transaction recording with full history
- `tick_zero_check` for bankruptcy detection
- Custom exceptions: `InsufficientFundsError`, `InsufficientItemsError`, `WalletNotFoundError`

### Agent Registry (`libs/streetmarket/registry/registry.py`)
- Register, get, require, list agents
- `AgentState` enum: ACTIVE, OFFLINE, INACTIVE
- Terminal INACTIVE state (cannot transition out)
- Profile and DeathInfo tracking
- Activity timestamp updates

### World State Store (`libs/streetmarket/world_state/store.py`)
- CRUD for Fields (with FieldStatus: empty/planted/growing/ready/flooded/depleted)
- CRUD for Buildings (owner, condition, features, occupants)
- Weather with WeatherEffect system
- Resources with quantity and conditions
- Property records (dict-based, flexible schema)

### Season Manager (`libs/streetmarket/season/manager.py`)
- UTC-based lifecycle: DORMANT → ANNOUNCED → PREPARATION → OPEN → CLOSING → ENDED
- Auto-transition to CLOSING at configurable threshold
- Auto-transition to ENDED at total ticks
- tick_to_utc / utc_to_tick conversions
- Snapshot for state serialization

### Ranking Engine (`libs/streetmarket/ranking/engine.py`)
- Weighted scoring: net_worth, survival_ticks, community_contribution
- Per-season history + overall rankings by owner
- Win tracking across seasons

### Tick Clock (`services/tick_clock/clock.py`)
- Async loop publishing to /system/tick
- single_tick() for testing
- Configurable via SeasonManager

### NATS Auth (`infrastructure/nats/nats-server.conf`)
- NKey-based auth templates for 4 roles (system, market agent, trading agent, viewer)
- Development mode: no auth (default)
- Production mode: commented-out authorization block

### Tests (209 total)
- `test_policy_engine.py` — 27 tests (loading, parsing, computed properties)
- `test_ledger.py` — 45 tests (wallets, inventory, transfers, batches, errors)
- `test_registry.py` — 33 tests (register, state transitions, profiles, listing)
- `test_world_state.py` — 45 tests (fields, buildings, weather, resources, properties)
- `test_season_manager.py` — 28 tests (lifecycle, ticking, auto-transitions, UTC conversions)
- `test_ranking_engine.py` — 17 tests (scoring, rankings, winners, overall)
- `test_tick_clock.py` — 14 tests (single tick, publishing, envelope validation)

## Issues encountered
- Ruff import sorting (I001) in several test files — auto-fixed
- Unused imports in ranking engine (field, Decimal, AgentState) — auto-fixed
- Long line in policy engine (closing_percent) — manually wrapped
- Tick clock had imports at bottom of file (E402) — moved to top
- Test file for season manager was written last by background agent (race condition)

## Key decisions
- All monetary operations use `Decimal` for exactness
- `LedgerInterface` is a `Protocol` (runtime_checkable) — enables future swap to blockchain
- FIFO batch tracking built into inventory from day one (for spoilage)
- Season phases auto-transition based on tick thresholds
- Weather uses an effects system (type, target, modifier, until_tick)

## How to verify
```bash
source .venv/bin/activate
pip install -e libs/
ruff check .
ruff format --check .
python -m pytest tests/ -x -q
# Expected: 209 passed
```

## Next step
Phase 2 — Market Agents (LLM Characters):
- Meteo (weather), Nature (world resources), Governor (validation + onboarding)
- Banker (transactions + ledger bridge), Landlord (property), Town Crier (narrator)
