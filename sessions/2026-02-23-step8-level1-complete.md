# Session: Step 8 — Complete Level 1 (LLM Nature + Rent + Bankruptcy + Storage + Baker + Builder)

**Date:** 2026-02-23
**Status:** COMPLETED
**Branch:** main
**Commit:** pending user commit

## Goal
Complete Maslow Level 1 by adding survival mechanics that make the economy meaningful:
1. Protocol layer: new message types (RENT_DUE, BANKRUPTCY, NATURE_EVENT), bread recipe, rent/storage constants
2. Storage limits: Banker checks inventory capacity before crediting items
3. Rent/Upkeep: Banker deducts 2 coins/tick rent, 20-tick grace, house exemption
4. Bankruptcy: Banker detects, Governor blocks bankrupt agents
5. LLM Nature Intelligence: NatureBrain calls Claude Haiku every 5 ticks with fallback
6. Agent SDK updates: handle new message types
7. Baker Agent: buys potatoes, crafts bread, sells bread
8. Builder Agent: buys walls+shelves+furniture, crafts houses, sells houses
9. Infrastructure: economy runner, Makefile, tests updated

## What was built
(updating as phases complete)

### Phase 1: Protocol Layer
- `libs/streetmarket/models/rent.py` — rent, bankruptcy, storage constants
- Updated `messages.py` — 3 new MessageTypes + payload models
- Updated `catalogue.py` — bread item + bread recipe
- Updated exports in `__init__.py` files
- Updated TS protocol

### Phase 2: Storage Limits
- Updated `services/banker/state.py` — storage helpers
- Updated `services/banker/rules.py` — storage checks on credit operations

### Phase 3: Rent / Upkeep
- Updated banker state, rules, and main agent for rent processing

### Phase 4: Bankruptcy
- Updated banker + governor for bankruptcy detection and blocking

### Phase 5: LLM Nature Intelligence
- Created `services/world/nature.py` — NatureBrain class
- Updated world state and engine for integration

### Phase 6: Agent SDK
- Updated agent state and base for new message types

### Phase 7: Baker Agent
- Created `agents/baker/` with strategy, agent, __main__, __init__

### Phase 8: Builder Agent
- Created `agents/builder/` with strategy, agent, __main__, __init__

### Phase 9: Infrastructure
- Updated run_economy.py, Makefile, test_economy_runner.py
- Updated agent strategies for bread fallback
- Updated TS protocol and strategy

## Issues encountered
- 19 lint issues after initial implementation (16 auto-fixable imports, 3 manual: 2 line-too-long, 1 E402 import order)
- Fixed by running `ruff check --fix .` + manual edits to nature.py, test_nature_brain.py, proof_of_life.py

## Key decisions
- Rent authority: Banker (owns wallets)
- Bankruptcy: Banker detects, Governor blocks
- Storage: Banker checks on credit operations
- LLM Nature: opt-in via WORLD_USE_LLM_NATURE env var
- Bread recipe: potato×3 → bread, 2 ticks, +20 energy

## How to verify
```bash
.venv/bin/pytest tests/ -v --ignore=tests/test_nats_client.py --ignore=tests/test_proof_of_life.py --ignore=tests/test_banker_integration.py --ignore=tests/test_governor_integration.py --ignore=tests/test_economy_integration.py --ignore=tests/test_world_integration.py
cd agents/lumberjack && npx vitest run
.venv/bin/ruff check .
```

## Next step
Step 9: Maslow Level 2 or integration testing of Level 1 mechanics
