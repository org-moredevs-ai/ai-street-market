# Session: Step 4 — World Engine (Tick Clock + Nature Spawns)

**Date:** 2026-02-19
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending — ready for commit)

## Goal
Implement the World Engine — the simulation's heartbeat. It broadcasts tick events, spawns raw materials each tick, and handles FCFS gathering by agents. Also update the Banker to credit inventory on successful gathers.

## What was built

### Phase 1: Shared Library Changes
- Added `SPAWN`, `GATHER`, `GATHER_RESULT` to `MessageType` enum
- Added `Spawn`, `Gather`, `GatherResult` payload models
- Updated `PAYLOAD_REGISTRY`, `models/__init__.py`, `streetmarket/__init__.py`
- Added model tests to `tests/test_models.py`

### Phase 2: WorldState
- `services/world/__init__.py` — Package marker
- `services/world/state.py` — WorldState, SpawnPool, DEFAULT_SPAWN_TABLE
- `tests/test_world_state.py` — Unit tests for state operations

### Phase 3: World Rules
- `services/world/rules.py` — process_tick, process_gather (pure functions)
- `tests/test_world_rules.py` — Unit tests for rule functions

### Phase 4: WorldEngine + Entry Point
- `services/world/world.py` — WorldEngine class (tick loop + gather handler)
- `services/world/__main__.py` — Entry point
- `Makefile` — Added `world` target

### Phase 5: Banker Modifications
- `services/banker/banker.py` — Added `/world/>` subscription + `_on_world_message` handler
- `services/banker/rules.py` — Added `process_gather_result` function
- `tests/test_banker_rules.py` — Added `TestProcessGatherResult` tests

### Phase 6: Integration Tests
- `tests/test_world_integration.py` — Full integration: ticks, spawns, gathers, banker credits

## Issues encountered
- Integration test `test_tick_publishing` initially asserted `tick_number == 1` but the subscription can be set up after the first tick fires (race condition). Fixed by checking consecutive ticks instead of absolute values.

## Key decisions
- Single "World" service handles both tick clock and nature spawns
- Spawn scope: raw materials only (potato, onion, wood, nails, stone)
- Spawn lifetime: one tick (replaced on next tick)
- Claiming: FCFS via spawn_id reference
- Partial grants supported (ask for 5, get 3 if only 3 left)
- Banker auto-creates account on gather if missing
- World skips own SPAWN and GATHER_RESULT messages (self-loop prevention)
- Tick interval configurable via WORLD_TICK_INTERVAL env var

## How to verify
```bash
# Unit tests (no NATS)
.venv/bin/pytest tests/test_world_state.py tests/test_world_rules.py tests/test_models.py tests/test_banker_rules.py -v

# All tests (requires NATS)
make infra-up && make test

# Run all services together
make world    # Terminal 1
make banker   # Terminal 2
make governor # Terminal 3

make infra-down
```

## Next step
Step 5 — TBD (first trading agent, or additional features)
