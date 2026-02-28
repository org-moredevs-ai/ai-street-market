# Session: Connect Local Agents to Staging

**Date:** 2026-02-28
**Status:** COMPLETED
**Branch:** main
**Commit:** (fill when done)

## Goal
Connect external demo agents (Python baker/farmer, TypeScript fisher) from local machine to staging NATS to test the full E2E flow.

## Configuration
- **Staging NATS:** `nats://mainline.proxy.rlwy.net:45295` (correct public TCP proxy)
- **LLM Model:** `google/gemini-2.5-flash-lite`
- **Season status:** OPEN (tick ~30 / 20160)

## What was built
- Verified Python agent deps installed (streetmarket from git)
- Verified TypeScript agent deps installed (node_modules present)
- Running baker + farmer (Python) and fisher (TypeScript) against staging

## Issues encountered
- Python agents needed `streetmarket` library reinstalled (ModuleNotFoundError)
  - Fixed with `.venv/bin/pip install -e ".[dev]"`
- Plan had wrong NATS proxy URL (`tramway.proxy.rlwy.net:43834`)
  - Correct URL from Railway: `mainline.proxy.rlwy.net:45295`
  - Found via `railway variables --service nats --environment staging`
- Baker wallet creation race condition (duplicate wallet error) — non-critical, wallet was created successfully

## How to verify
1. Check staging market logs: `railway logs --service market --environment staging`
2. Check viewer: `https://viewer-staging-3e74.up.railway.app`
3. Look for agent join requests and Governor accept/reject messages

## Results
- All 3 agents connected and running
- Wallets created: baker (100), farmer (100), fisher (100)
- LLM calls flowing on both agent and market sides
- Season OPEN at tick ~40 / 20160

## Running processes
- **Python (baker + farmer):** background task `b6n6tveo0`
- **TypeScript (fisher):** background task `b8wmabzeu`
- Stop with Ctrl+C or `TaskStop`

## Commands to re-run
```bash
# Python agents
cd /Users/hugocasqueiro/sourcecode/repos/org-moredevs-ai/ai-street-market-agents-py
NATS_URL=nats://mainline.proxy.rlwy.net:45295 \
OPENROUTER_API_KEY=sk-or-v1-296b... \
DEFAULT_MODEL=google/gemini-2.5-flash-lite \
.venv/bin/python scripts/run.py baker farmer

# TypeScript agent
cd /Users/hugocasqueiro/sourcecode/repos/org-moredevs-ai/ai-street-market-agents-ts
NATS_URL=nats://mainline.proxy.rlwy.net:45295 \
OPENROUTER_API_KEY=sk-or-v1-296b... \
OPENROUTER_MODEL=google/gemini-2.5-flash-lite \
npx tsx src/run.ts fisher
```

## Next step
- Monitor agent behavior over several ticks
- Check viewer at https://viewer-staging-3e74.up.railway.app shows agent messages
- Consider running all agents (woodcutter, merchant, builder) once flow is verified
