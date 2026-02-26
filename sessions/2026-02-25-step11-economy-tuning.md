# Session: Step 11 Part 2 — Economy Tuning & Market Experience

**Date:** 2026-02-25
**Status:** COMPLETED
**Branch:** main
**Commits:** 00204ad (economy balance + market experience)

## Goal
Fix the economy so agents actually trade profitably, the Town Crier narrates dramatically, and the viewer frontend shows a living market.

## What was built

### Economy Balance Fixes
- **Rent reduced** from 2.0/tick to 0.5/tick — with rate-limited LLM calls (1 agent per tick), agents couldn't earn enough to cover old rent
- **Grace period** extended from 20 to 50 ticks
- **Bankruptcy grace** from 5 to 15 ticks
- Result: at tick 33, all 6 agents healthy ($83-$131), 0 bankruptcies

### Spawn TTL (fixes gather failures)
- Resources now survive 3 ticks instead of 1 (`SPAWN_TTL = 3`)
- With LLM agents taking 1-3s to respond, gathers from the previous tick's spawn were always rejected
- `_recent_spawns` dict replaces single `_active_spawn`

### Market Experience
- **Staggered agent entry** — 10 seconds between each agent launch
- **Town Crier welcome narrations** — narrates at tick 1 ("market open") and each agent join
- **Narration interval** set to 5 ticks (every 25 seconds)
- **Narration body limit** raised to 1000 chars (was 500), prompt instructs LLM to stay under 800
- **Agent name mapping** in narrator prompt (farmer-01 = "Farmer Joe", etc.)

### NATS Stream Purge
- Critical fix: old JetStream data caused tick mismatches (Banker at tick 191 vs World at tick 7)
- Must purge stream between runs: `jsm.purge_stream('STREETMARKET')`

## Issues encountered

1. **Tick mismatch between services** — Old NATS JetStream messages from previous runs confused the Banker/Governor. Fix: purge stream before each run.
2. **Narration body too long** — Pydantic `Narration` model had `max_length=500` but the LLM (arcee-ai/trinity-large-preview:free) generates 600-900 chars. Fixed at both the model level (1000) and prompt level ("under 800").
3. **Gathers always failing** — Single active spawn replaced every tick; LLM response delay meant gather used expired spawn. Fixed with TTL-based spawn pool.

## Key decisions
- Rent at 0.5 is sustainable even with slow trading (1 agent/tick)
- Spawn TTL of 3 ticks is enough for the 5-second tick interval + LLM latency
- Welcome narrations add personality without busting rate limits

## How to verify
```bash
# Purge NATS first
python -c "import asyncio,nats; asyncio.run((lambda: ...)())"
# Or restart NATS: make infra-down && make infra-up

# Start economy
make run-economy

# Check health via WebSocket bridge
python -c "import asyncio,json,websockets; ..."
# All wallets > $80, 0 bankruptcies, trades happening
```

## Next step
- Improve frontier viewer experience (agent avatars, animations)
- Consider paid model for demos ($0.50 for 30 min with Claude Haiku)
- Action queuing: LLM decides once, executes across multiple ticks
- Agent memory: remember past trades across sessions
