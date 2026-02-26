# Session: Phase 2 — Market Agents (LLM Characters)

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Build the 6 LLM-powered market agents that form the intelligence layer:
- Meteo (weather), Nature (resources), Governor (validation/onboarding)
- Banker (transactions/ledger bridge), Landlord (property), Town Crier (narrator)

Plus supporting infrastructure:
- LedgerEvent model for structured events on /system/ledger
- MarketAgent base class (NATS subscription, LLM reasoning, event emission)

## What was built

### LedgerEvent model (`libs/streetmarket/models/ledger_event.py`)
- `LedgerEvent` Pydantic model for structured events on /system/ledger
- `EventTypes` constants class with 18 event types (trade, wallet, inventory, property, agent, world, economy, season)
- Bridge between LLM reasoning and deterministic execution

### MarketAgent base class (`libs/streetmarket/agent/market_agent.py`)
- Abstract base for all market infrastructure agents
- NATS topic subscription routing (tick vs. other messages)
- LLM reasoning with injectable llm_fn (for testing) or LLMConfig
- `reason()` → raw text, `reason_json()` → extracted JSON
- `respond()` → NL response on public topics
- `emit_event()` → structured LedgerEvent to /system/ledger
- `_route_message()` → skips own messages, routes tick/non-tick
- `create_llm_fn()` factory using LangChain + OpenRouter

### Meteo (`services/meteo/meteo.py`)
- Weather oracle: generates forecasts at configurable intervals
- Reads world state weather, reasons via LLM about patterns
- Emits weather_change events with condition, temperature, wind, effects
- Publishes NL forecasts to /market/weather

### Nature (`services/nature/nature.py`)
- Living world: evaluates field growth, resource replenishment
- Reads all fields and resources from WorldStateStore
- Emits field_update events (status, crop, ready_tick)
- Emits resource_update events (quantity_delta, reason)
- Reacts to weather changes from Meteo via /system/ledger

### Governor (`services/governor/governor.py`)
- Trade validator and market authority
- Onboarding: detects join messages, accepts/rejects via LLM reasoning
- Trade validation: evaluates proposals, approves/rejects
- Emits agent_registered, agent_rejected, trade_approved, trade_rejected events
- Publishes NL responses to /market/square

### Banker (`services/banker/banker.py`)
- Transaction processor and ledger bridge
- Processes structured events from /system/ledger
- Creates wallets on agent_registered, executes trades on trade_approved
- Collects fines and rent via wallet debit operations
- Responds to bank inquiries on /market/bank with LLM reasoning
- Handles InsufficientFunds/InsufficientItems/WalletNotFound errors

### Landlord (`services/landlord/landlord.py`)
- Property manager: rent collection at configurable intervals
- Skips agents in grace period (configurable, default 50 ticks)
- Exempts house owners from rent
- Handles property inquiries on /market/property
- Emits rent_collected events

### Town Crier (`services/town_crier/narrator.py`)
- Entertainment narrator: generates dramatic stories
- Subscribes to ALL public topics + /system/ledger
- Collects events, generates narrations at intervals
- Publishes to /market/news
- Truncates narration to 800 chars
- Does NOT emit ledger events (purely entertainment)

### Tests (93 new, 302 total)
- `test_ledger_event.py` — 30 tests (model, EventTypes, serialization)
- `test_market_agent.py` — 63 tests (base class + all 6 agents with mocked LLM)

## Issues encountered
- Missing `Envelope` imports in agent files that reference it in type hints
- Unused imports (Weather, FieldStatus, etc.) in agent files
- `remove_item` in Banker passed extra `tick` param — fixed to match ledger interface
- Import sorting issues in nature.py — auto-fixed by ruff
- Line length issues in test file — manually wrapped

## Key decisions
- LLM function injectable via `llm_fn` parameter for full test control
- MarketAgent skips its own messages to prevent feedback loops
- Banker is unique: both LLM reasoning AND direct ledger access
- Town Crier is entertainment-only: no ledger events emitted
- Governor detects joins via keyword matching in NL messages
- All agents use `reason_json()` for structured decisions, `reason()` for NL responses

## How to verify
```bash
source .venv/bin/activate
ruff check . && ruff format --check .
python -m pytest tests/ -x -q
# Expected: 302 passed
```

## Next step
Phase 3 — Agent SDK v2 + External Repos
