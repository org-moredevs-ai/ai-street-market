# Session: Phase 4 — Frontend v2 (WebSocket Bridge + Viewer Protocol)

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending)

## Goal
- Build WebSocket bridge service (NATS → WebSocket for browser clients)
- Define viewer protocol (what data the frontend receives)
- NOTE: Full frontend UI (ai-street-market-viewer) needs separate repo + user action

## What was built

### WebSocket Bridge (`services/websocket_bridge/bridge.py`)
- Connects to NATS and subscribes to all public market topics + tick
- Runs a WebSocket server (default port 9090)
- Forwards NL messages from NATS to all connected WS clients as `{"type":"message"}`
- Sends recent message history (`{"type":"history"}`) on client connect (up to 200 messages)
- Sends world state snapshot (`{"type":"state"}`) on connect
- Includes: agents from registry, weather, fields, buildings, season info
- `broadcast_state()` method for periodic state pushes
- Dead client cleanup (removes closed connections on send failure)
- Read-only: viewer clients cannot publish back to NATS

### Viewer Protocol Documentation (`docs/VIEWER-PROTOCOL.md`)
- Complete protocol specification for frontend clients
- Message types: `message`, `history`, `state`
- State snapshot schema (agents, weather, fields, buildings, season)
- Topic reference table
- Agent states and season phases
- JavaScript client example

### Tests (`tests/test_websocket_bridge.py` — 19 tests)
- Envelope conversion to viewer-friendly dict
- Construction with/without components
- NATS handlers: tick update, message relay, history buffer, dead client cleanup
- State snapshots: minimal, with registry, with world state, with fields, buildings, season
- State broadcast to clients
- Multiple topics forwarded, multiple clients receive same message
- Lifecycle: stop clears clients and connections

## Issues encountered
- WorldStateStore methods are all async — used direct dict access for sync snapshot builder
- Field uses `id` not `field_id`, Building uses `id` not `building_id`, `type` not `building_type`
- Weather.temperature is `str` ("mild") not `float`, and Weather has no `description` field
- AgentRecord uses `id` not `agent_id`; AgentRegistry.register() is async and needs `owner` param
- SeasonConfig has computed properties (total_ticks, closing_tick), not constructor args
- Refactoring broke snapshot builder (return statement inside extracted method left world state code unreachable)

## Key decisions
- Bridge uses a standalone WebSocket server (port 9090), not NATS native WS (port 8080)
- Viewer protocol is read-only (no client → server messages)
- State snapshot accesses internal store dicts directly (sync) instead of calling async methods
- Ranking excluded from sync snapshot (requires async call + season number)
- Full frontend UI deferred to separate viewer repo

## How to verify
```bash
source .venv/bin/activate
ruff check . && ruff format --check .
python -m pytest tests/ -x -q  # 355 tests pass
```

## Next step
- Full frontend UI needs separate `ai-street-market-viewer` repo — needs Hugo's action
- Phase 5 — Season Framework
