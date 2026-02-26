# Session: Phase 3 — Agent SDK v2 + External Repos

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
- Build Trading Agent SDK (the framework for external agents)
- Create documentation for building agents
- Create demo agent templates
- NOTE: External repos (ai-street-market-agents-py/ts) need user action

## What was built

### TradingAgent SDK (`libs/streetmarket/agent/trading_agent.py`)
- Base class for external trading agents
- Connection management: `connect()`, `disconnect()`
- Market joining: `join(introduction)` — triggers Governor onboarding
- Communication: `say()`, `offer()`, `bid()`, `ask_banker()`, `ask_landlord()`
- LLM reasoning: `think()` (raw text), `think_json()` (structured)
- Event routing: auto-subscribes to all public topics + agent inbox
- Run loop: `run(until_tick=N)` with `stop()` support
- Injectable LLM via `llm_fn` or `LLMConfig`

### Templates
- **Python** (`templates/python/my_agent.py`): MyAgent subclass with LLM decision-making
- **TypeScript** (`templates/typescript/my_agent.ts`): Direct NATS/JetStream client

### Documentation
- `docs/BUILDING_AN_AGENT.md`: Complete getting started guide
  - Quick starts for Python and TypeScript
  - Communication model explanation
  - Topics reference table
  - Lifecycle walkthrough
  - Key methods reference
  - Advanced: custom LLM config, no-SDK usage, testing

### Tests (`tests/test_trading_agent.py` — 34 tests)
- Construction: basic, default display name, injected LLM, initial state, LLMConfig
- Connection: subscribes to 8 topics, disconnect, disconnect without connect
- Joining: sends on square, raises without connect
- Communication: say, offer, bid, ask_banker, ask_landlord, raise without connect
- LLM reasoning: think, think_json, no-LLM fallbacks, error handling, non-JSON handling
- Envelope routing: tick updates, message routing, own-message skip, inbox routing
- Run loop: until_tick, stop method
- Subclass integration: full tick+message flow, LLM decision flow
- Export checks: importable from agent package and top-level

### Exports
- Updated `libs/streetmarket/agent/__init__.py` — exports `TradingAgent`
- Updated `libs/streetmarket/__init__.py` — exports `TradingAgent`

## Issues encountered
- `create_llm_fn` is a lazy import inside `__init__` — had to patch `streetmarket.agent.market_agent.create_llm_fn` not `trading_agent.create_llm_fn`
- `LLMConfig` is a dataclass with `api_base` not `base_url`, and requires all 5 fields

## Key decisions
- TradingAgent is completely separate from MarketAgent — different base classes for different roles
- External agents only see public topics (no `/system/ledger`)
- No dependency on market internals — agents could be in separate repos
- TypeScript template uses raw NATS (no SDK), Python template uses streetmarket SDK

## How to verify
```bash
source .venv/bin/activate
ruff check . && ruff format --check .
python -m pytest tests/ -x -q  # 336 tests pass
```

## Next step
- External repos (ai-street-market-agents-py/ts) need Hugo to create
- Phase 4 — Frontend v2
