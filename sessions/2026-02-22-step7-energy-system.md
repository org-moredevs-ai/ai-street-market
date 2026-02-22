# Session: Step 7 — Energy System + Mason Agent

**Date:** 2026-02-22
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Add a server-side energy system that creates real scarcity, forces trade, and makes food/shelter essential. Also add the Mason agent (gathers stone, buys wood, crafts walls).

## What was built

### Phase 1: Protocol Layer
- `libs/streetmarket/models/energy.py` — energy constants (STARTING=100, MAX=100, REGEN=5/tick, SHELTER_BONUS=3, action costs)
- 3 new MessageTypes: CONSUME, CONSUME_RESULT, ENERGY_UPDATE
- 3 new payload models: Consume, ConsumeResult, EnergyUpdate
- `agent_id` field added to ValidationResult (World needs to know who acted)
- `energy_restore` field added to CatalogueItem (soup=30.0)
- CONSUME added to ActionKind; `energy` field added to AgentState (default=100.0)

### Phase 2: World Engine Energy Tracking
- WorldState: `_energy` dict, `_sheltered` set, register/get/set/deduct/add energy methods
- Rules: check_gather_energy, deduct_gather_energy, apply_regen, get_energy_cost, process_consume_result
- WorldEngine: subscribes to /market/governance + /market/bank, publishes ENERGY_UPDATE, energy-checks GATHER, processes CONSUME_RESULT

### Phase 3: Governor Energy Validation
- GovernorState: `_agent_energy` dict with update_energy/get_energy methods
- Rules: energy check before allowing actions, _validate_consume (checks item is consumable)
- Governor: handles ENERGY_UPDATE on tick topic, adds agent_id to ValidationResult

### Phase 4: Banker CONSUME Processing
- Rules: ConsumeResultData dataclass, process_consume function
- Banker: handles CONSUME messages, publishes CONSUME_RESULT

### Phase 5: Agent SDK + Existing Agent Updates
- TradingAgent: ENERGY_UPDATE handler updates state.energy, CONSUME execution via /market/food
- Farmer strategy: consume soup <30 energy, rest when <10
- Chef strategy: consume soup <30 energy, rest when <10, keeps 1 soup reserve

### Phase 6: Mason Agent
- `agents/mason/` — MasonAgent(TradingAgent), strategy.py, __main__.py
- Gathers stone(8), buys wood at <=1.5x base, crafts wall (stone×4+wood×2), sells wall at 18.0
- Energy-aware: consume soup <30, rest <10
- Accepts wall bids at >=15.0, bids for wood at 1.3x when needed

### Phase 7: TypeScript Lumberjack Update
- protocol.ts: +CONSUME, CONSUME_RESULT, ENERGY_UPDATE message types
- state.ts: +energy field (default 100)
- strategy.ts: energy-aware (consume soup, rest when critical, bid for soup)
- index.ts: ENERGY_UPDATE handler, consume/bid action execution

### Phase 8: Infrastructure
- run_economy.py: added Mason service definition (phase 3, bright yellow)
- Makefile: added `mason` target
- test_economy_runner.py: updated service count 6→7, added mason to phase 3 agents

## Issues encountered
1. **test_agent_sdk.py::test_all_kinds_exist** — adding CONSUME to ActionKind broke the test that checked all kinds. Fixed by adding "consume" to expected set.
2. **13 governor rule tests failed** — after adding energy checks, tests with no energy snapshot had agents at 0 energy, blocking all actions. Fixed with `_state_with_energy()` helper.
3. **2 economy runner tests failed** — service count/agent set hardcoded to 6/3 agents. Updated to 7/4 with mason.
4. **Lint issues** — import sorting, unused imports (auto-fixed), line-length in test files (manually fixed).

## Key decisions
- World Engine is sole energy authority (physical property of agents)
- Governor reads energy snapshot, gates market actions; World deducts on valid
- GATHER bypasses Governor → World checks energy directly
- CONSUME is free (0 energy cost) — starving agents must be able to eat
- At zero energy: only CONSUME, ACCEPT, JOIN, HEARTBEAT allowed
- Chef keeps 1 soup reserve for emergency self-consumption

## Test counts
- Python unit tests: 451 (was 343, +108 new)
- TypeScript tests: 22 (was 14, +8 new)
- **Total: 473 tests**

## How to verify
```bash
# Unit tests (no NATS)
.venv/bin/pytest tests/ -v --ignore=tests/test_nats_client.py --ignore=tests/test_proof_of_life.py --ignore=tests/test_banker_integration.py --ignore=tests/test_governor_integration.py --ignore=tests/test_economy_integration.py --ignore=tests/test_world_integration.py

# TypeScript tests
cd agents/lumberjack && npx vitest run

# Lint
.venv/bin/ruff check .

# Full economy (needs NATS)
make infra-up && make run-economy
```

## Next step
- Step 8: Shelter system (houses provide shelter bonus regen) + Builder agent
- Or: integration testing of energy system end-to-end with NATS
