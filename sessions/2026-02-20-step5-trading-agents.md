# Session: Step 5 — Trading Agents (Farmer, Chef, Lumberjack)

**Date:** 2026-02-20
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Bring the economy to life with 3 autonomous trading agents that prove the protocol works for external developers. Add an Agent SDK to the shared library, implement Farmer (Python), Chef (Python), and Lumberjack (TypeScript) agents.

## What was built

### Phase 1: Topic Map Helper
- `libs/streetmarket/helpers/topic_map.py` — maps item name → market topic via catalogue category
- Updated `helpers/__init__.py` and `streetmarket/__init__.py` exports
- `tests/test_topic_map.py` — 12 tests

### Phase 2: Agent SDK
- `libs/streetmarket/agent/actions.py` — `ActionKind` enum + `Action` frozen dataclass
- `libs/streetmarket/agent/state.py` — `AgentState`, `CraftingJob`, `PendingOffer`, `ObservedOffer`
- `libs/streetmarket/agent/base.py` — `TradingAgent` abstract base class with auto-join, auto-heartbeat, auto-craft-complete, action execution, market/nature message handling
- `libs/streetmarket/agent/__init__.py` — SDK package exports
- Updated `streetmarket/__init__.py` to export Agent SDK types
- `tests/test_agent_sdk.py` — 25 tests

### Phase 3: Farmer Agent
- `agents/farmer/strategy.py` — pure `decide()`: GATHER potato+onion, ACCEPT bids at base price, OFFER surplus at 1.2x
- `agents/farmer/agent.py` — `FarmerAgent(TradingAgent)`
- `agents/farmer/__main__.py` — entry point
- `tests/test_farmer_strategy.py` — 18 tests

### Phase 4: Chef Agent
- `agents/chef/strategy.py` — pure `decide()`: ACCEPT cheapest ingredient offers, CRAFT soup, OFFER soup, BID for ingredients
- `agents/chef/agent.py` — `ChefAgent(TradingAgent)`
- `agents/chef/__main__.py` — entry point
- `tests/test_chef_strategy.py` — 18 tests

### Phase 5: Lumberjack Agent (TypeScript)
- `agents/lumberjack/src/protocol.ts` — Envelope interface, MessageType, Topics, createMessage(), toNatsSubject(), topicForItem()
- `agents/lumberjack/src/state.ts` — AgentState + helper functions
- `agents/lumberjack/src/strategy.ts` — pure decide(): GATHER wood+nails, CRAFT shelf, OFFER shelf, ACCEPT bids
- `agents/lumberjack/src/index.ts` — NATS entry point with full protocol loop
- `agents/lumberjack/src/strategy.test.ts` — 14 vitest tests

### Phase 6: Integration Test
- `tests/test_economy_integration.py` — 4 tests (agents join, farmer gathers, farmer offers, full economy cycle)

### Phase 7: Finalize
- Updated `Makefile` with `farmer`, `chef`, `lumberjack` targets
- Updated `.gitignore` for `agents/lumberjack/node_modules/`
- Fixed all lint issues (ruff clean except pre-existing proof_of_life.py E402)

## Test Results
- **Python unit tests:** 290 passed (73 new + 217 existing)
- **TypeScript tests:** 14 passed
- **Total new tests:** 87

## Issues encountered
- Import ordering: ruff requires alphabetical imports — agent SDK import in `__init__.py` needed reordering
- Unused imports in `base.py`: `asyncio` and `parse_payload` not needed, cleaned up
- Line length: several test lines exceeded 100 chars, broke into multi-line

## Key decisions
- Agents live in `agents/` (not `services/`) — they are external participants, not infrastructure
- Agent SDK lives in `libs/streetmarket/agent/` — anyone who installs streetmarket gets it
- Strategy as pure functions `decide(state) → list[Action]` for full testability without NATS
- Lumberjack in TypeScript to prove language-agnostic protocol
- Open registration: agents self-register via JOIN on first tick

## How to verify
```bash
# Python unit tests (no NATS)
.venv/bin/pytest tests/test_topic_map.py tests/test_agent_sdk.py tests/test_farmer_strategy.py tests/test_chef_strategy.py -v

# TypeScript unit tests (no NATS)
cd agents/lumberjack && npx vitest run

# All non-integration tests
.venv/bin/pytest tests/ -k "not integration" -v

# Full economy (each in separate terminal, requires NATS)
make infra-up
make world
make governor
make banker
make farmer
make chef
make lumberjack
```

## Next step
Step 6 — TBD (possible: dashboard/observer, more agents, persistence, or game master)
