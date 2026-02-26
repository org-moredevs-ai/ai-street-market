# Session: Deployment Script — Wire Everything Together

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
Create `scripts/run_season.py` — the deployment script that wires all components (infrastructure, market agents, tick clock, WebSocket bridge) into a running season. This is the integration point that connects everything built in Phases 0–5.

## What was built

### scripts/run_season.py
- CLI orchestration script with argparse
- Loads season + world policy from YAML via PolicyEngine
- Creates all deterministic infrastructure (Ledger, Registry, WorldState, SeasonManager, RankingEngine)
- Validates LLM environment variables (OPENROUTER_API_KEY, DEFAULT_MODEL)
- Connects to NATS and purges stale JetStream messages
- Creates and starts all 6 market agents (Governor, Banker, Nature, Meteo, Landlord, Town Crier)
- Optionally starts WebSocket bridge for viewer
- Runs tick clock through full season lifecycle
- Computes final rankings and prints results
- Handles graceful shutdown on CTRL+C (SIGINT/SIGTERM)

### tests/test_run_season.py
- Tests for wiring logic (env validation, agent creation, argument parsing)
- All tests mock LLM and NATS — no real connections needed

### Makefile updates
- `run-season` and `run-season-fast` targets

### .env.example updates
- Documented env vars for deployment

## Issues encountered
- E402 lint errors: `sys.path.insert` before imports requires `# noqa: E402` on each import line
- Import sorting: ruff's isort expects `streetmarket.*` as third-party before `scripts.*`/`services.*` as first-party
- No git repository initialized — cannot commit

## Key decisions
- Script uses `sys.path.insert` to add project root, with `# noqa: E402` for all subsequent imports
- `create_market_agents()` is a standalone function (not a class method) for testability
- Tick override creates a new `SeasonConfig` with the overridden interval (frozen dataclass)
- Signal handling via `asyncio.Event` for clean shutdown coordination
- Progress logging every 10 ticks via background monitor task
- WebSocket bridge gets its own NATS connection (via its internal `MarketBusClient`)

## How to verify
```bash
source .venv/bin/activate
ruff check . && ruff format --check .
python -m pytest tests/ -x -q  # 397 tests pass
```

## Next step
- Initialize git repository and commit all work
- Create external agent repos (ai-street-market-agents-py/ts)
- Full frontend UI (ai-street-market-viewer)
- NATS NKey auth configuration for production
- Live test with NATS running (`make infra-up && make run-season-fast`)
