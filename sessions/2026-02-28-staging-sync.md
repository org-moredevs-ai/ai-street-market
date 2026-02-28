# Session: Staging/Production Environment Sync

**Date:** 2026-02-28
**Status:** COMPLETED
**Branch:** main
**Commit:** 6a66c3a

## Goal
Fix staging environment to match production behavior. Both environments should run the market with full world state, embedded WebSocket bridge, and paid LLM model.

## What was built

### 1. Diagnosed staging vs production differences
Compared all env vars across both environments for market, viewer, and ws-bridge services. Found 9 configuration mismatches caused by manual production fixes not being applied to staging.

### 2. Fixed staging env vars
- `DEFAULT_MODEL`: free → paid (`google/gemini-2.5-flash-lite`)
- `TICK_OVERRIDE`: 2 → 30 (30s ticks)
- `PORT`: missing → 9090
- `SERVICE_ROLE`: missing → market
- `CLEAR_SNAPSHOTS`: missing → 1 (one-time cleanup)

### 3. Cleared broken startCommand on staging market
- Railway's `startCommand` doesn't inherit Docker PATH → `python3` not found
- Cleared via Railway GraphQL API: `serviceInstanceUpdate(input: { startCommand: "" })`

### 4. Fixed staging viewer WS URL
- Was pointing to standalone ws-bridge (`wss://ws-bridge-staging.up.railway.app`)
- Updated to market bridge (`wss://market-staging.up.railway.app`)

### 5. Created new Railway staging token
- Old token was scoped to deleted staging environment
- Created new token via GraphQL: `projectTokenCreate(input: { projectId, environmentId, name: "staging-ci-v2" })`
- Updated GitHub secret: `RAILWAY_TOKEN` in staging environment

### 6. Fixed CI pipeline
- Test `test_load_season_config` expected old dates (Mar 15) — updated to match current `season-1.yaml` (Feb 28)
- Docker build referenced `target: market` and `target: ws-bridge` — removed (Dockerfile is single-stage)
- Added `workflow_dispatch` trigger for manual reruns

### 7. Verified both environments
- Both markets respond on HTTPS with WebSocket server message
- Both viewers return correct WS URL from `/api/config`
- Both WebSocket endpoints send full world state (weather, season, agents)
- CI pipeline ALL GREEN: lint, test (420), build, deploy staging, deploy production

## Issues encountered
- Railway MCP `get-logs` returned stale logs from old deployments, not the current one
- `serviceInstanceRedeploy` via GraphQL uses Docker Hub image (RAILPACK), not Dockerfile — but works because CI pushes updated images
- CI staging deploy was stuck in DEPLOYING for 20+ minutes — cancelled and redeployed via GraphQL
- `gh api` for approving deployments needs JSON body via `--input`, not `-f` flags (integer type issue)
- WebFetch caches responses — `curl` needed for real-time verification

## Key decisions
- Both environments use paid model (`gemini-2.5-flash-lite`) — free model rate limits are impractical
- Staging market runs as Dockerfile-deployed service (same as production) via CI
- `CLEAR_SNAPSHOTS` reset to 0 after initial cleanup to preserve state on restarts

## How to verify
```bash
# CI — should be all green
gh run list --repo org-moredevs-ai/ai-street-market -L 1

# Both viewers return correct WS URLs
curl -s https://viewer-production-95af.up.railway.app/api/config
curl -s https://viewer-staging-3e74.up.railway.app/api/config

# Both markets respond (WebSocket server)
curl -s https://market-production-cd1e.up.railway.app
curl -s https://market-staging.up.railway.app
```

## Next step
- Run demo agents to generate market traffic
- Verify viewer displays messages in browser
- Consider deploying agents to Railway
