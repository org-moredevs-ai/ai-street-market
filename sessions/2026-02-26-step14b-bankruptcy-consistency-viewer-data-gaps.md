# Session: Step 14B — Bankruptcy Consistency + Viewer Data Gaps

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Fix 20 inconsistencies found after running economy 857+ ticks with all agents bankrupt:
1. Backend: Reject actions from bankrupt agents (Banker, World, Town Crier)
2. Bridge: Freeze bankrupt agent data, guard handlers, add chatter/events to snapshot, infer halt
3. Viewer: Bankruptcy guards in store, populate chatter/events from snapshot, dead code cleanup
4. Tests: ~21 new backend tests

## What was built

### Phase 1: Backend Bankruptcy Guards
- [x] 1.1 Banker: reject actions from bankrupt agents in `_on_market_message` (except JOIN)
- [x] 1.2 Banker: reject gather_result for bankrupt agents in `process_gather_result()`
- [x] 1.3 Banker: reject trades involving bankrupt agents in `process_accept()`
- [x] 1.4 Banker: skip bankrupt agents in `process_spoilage()`
- [x] 1.5 World: block consume_result for bankrupt agents
- [x] 1.6 World: explicit bankruptcy check on GATHER with immediate GATHER_RESULT failure
- [x] 1.7 World: filter bankrupt agents from energy_update
- [x] 1.8 Town Crier: `_economy_halted` flag — skip LLM calls after halt
- [x] 1.9 Town Crier: filter bankrupt agents from weather energy calculation

### Phase 2: Bridge Data Consistency
- [x] 2.1 Freeze bankrupt agent data (wallet=0, energy=0) on bankruptcy
- [x] 2.2 Guard heartbeat, agent_status, settlement, rent_due, energy_update for bankrupt agents
- [x] 2.3 Infer economy halt from all-bankrupt state (handles missed ECONOMY_HALT)
- [x] 2.4 Add recent_chatter (maxlen=150) to snapshot — populated from 8 event handlers
- [x] 2.5 Add recent_events (maxlen=200) to snapshot — populated from bridge._on_message

### Phase 3: Viewer Store
- [x] 3.1 Bankruptcy guards in event handlers: heartbeat, energy_update, settlement, agent_status, rent_due
- [x] 3.2 Stop processing state updates after economy halt (events still logged)
- [x] 3.3 Populate chatterFeed from snapshot's `recent_chatter` (solves empty Market page)
- [x] 3.4 Populate events from snapshot's `recent_events` (solves empty Events page)
- [x] 3.5 Prune expired nature events on tick
- [x] 3.6 Header uses dynamic `haltReason` from store

### Phase 4: Tests — 21 new
- [x] Banker rejects offer/bid from bankrupt agents (2 tests)
- [x] Banker rejects gather_result for bankrupt agents (2 tests)
- [x] Banker rejects accept involving bankrupt buyer/seller (3 tests)
- [x] Banker skips bankrupt agents in spoilage (2 tests)
- [x] Bridge freezes wallet/energy on bankruptcy + adds chatter (2 tests)
- [x] Bridge guards heartbeat/agent_status/settlement/rent_due/energy for bankrupt (5 tests)
- [x] Bridge infers economy halt from all-bankrupt state (2 tests)
- [x] Bridge snapshot includes recent_chatter + recent_events (3 tests)

### Phase 5: Viewer Cleanup
- [x] Deleted 7 dead files: narration-feed.tsx, narration-card.tsx, weather-badge.tsx, price-table.tsx, price-sparkline.tsx, settlement-feed.tsx, lib/scoring.ts
- [x] Added missing event filter buttons: economy_halt, item_spoiled, heartbeat

## Issues encountered
1. `on_energy_update` used `.update()` instead of full replacement — broke existing test `test_replaces_previous`. Fixed by doing full replacement then re-zeroing bankrupt agents.
2. Town Crier test factory uses `__new__` (bypasses `__init__`) — needed to set `_economy_halted = False` in test helper.

## Key decisions
- Bridge `on_energy_update` does full replacement (to match existing behavior) then re-freezes bankrupt agents at 0.
- Chatter entries from snapshot use a `chatterTextFromSnapshot()` helper to reconstruct display text from raw backend data.
- Events from snapshot are reversed (newest first) to match the store's display order.

## How to verify
```bash
# Backend (1013 tests pass, 11 integration skipped)
source .venv/bin/activate
pip install -e libs/
python -m pytest tests/ -x --ignore=tests/test_nats_client.py --ignore=tests/test_proof_of_life.py --ignore=tests/test_banker_integration.py --ignore=tests/test_world_integration.py -q

# Viewer
cd ../ai-street-market-viewer && npx tsc --noEmit
```

## Next step
Step 15 — Offer Expiration + Counter Offers
