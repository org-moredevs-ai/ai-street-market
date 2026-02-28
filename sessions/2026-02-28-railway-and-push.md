# Session: Railway Setup, Secrets, and Push All Repos

**Date:** 2026-02-28
**Status:** COMPLETED
**Branch:** main
**Commit:** 43d4e1e (main repo), b36eed2 (viewer)

## Goal
Use Railway MCP to inspect project state, create staging environment, set up viewer service, configure RAILWAY_TOKEN secrets at repo level, and commit+push all repos.

## What was built

### 1. Railway project inspection
- Project: `ai-street-market` (b246a465-32a4-49bc-bae5-ef9a4ee3c369)
- Services: market, ws-bridge, nats (all configured with env vars)
- Originally only had `production` environment

### 2. Railway staging environment
- Created `staging` environment by duplicating `production` via Railway MCP
- All vars inherited (NATS_URL, OPENROUTER_API_KEY, model config, etc.)

### 3. Viewer service on Railway
- Created `viewer` service via `railway add --service viewer`
- Now 4 services: market, ws-bridge, nats, viewer

### 4. CI workflows updated with --environment flags
- Main repo: `railway up --service X --environment staging/production --ci`
- Viewer repo: `railway up --service viewer --environment staging/production --ci`
- Uses project-level token (not env-scoped) + explicit environment flag

### 5. GitHub secrets — hierarchical (repo > environment)
- **Main repo**: RAILWAY_TOKEN + DOCKER_HUB_* at repo level, OPENROUTER_API_KEY at env level
- **Viewer repo**: RAILWAY_TOKEN at repo level
- Hierarchy: repo-level defaults, env-level overrides where values differ

### 6. Viewer ESLint fixed for Next.js 16
- `next lint` removed in Next.js 16 — switched to `eslint .` with native flat config
- Removed `FlatCompat` bridge (caused circular reference errors)
- Fixed react-hooks/set-state-in-effect and react-hooks/refs lint errors
- Removed unused `@eslint/eslintrc` dependency

### 7. All 4 repos committed and pushed
- `ai-street-market`: CI with real Railway deploys (43d4e1e)
- `ai-street-market-viewer`: CI/CD + Dockerfile + ESLint fixes (5e5f540, b36eed2)
- `ai-street-market-agents-py`: already clean and pushed
- `ai-street-market-agents-ts`: already clean and pushed

### 8. Dockerfile fixes for Railway
- **Main repo**: Railway bans `VOLUME` keyword — replaced `VOLUME /data/snapshots` with `RUN mkdir -p /data/snapshots`
- **Viewer repo**: `COPY --from=builder /app/public ./public` failed because `public/` not tracked in git — added `RUN mkdir -p public` before build
- Both fixes committed and pushed (7fdc7a2 main repo, new commit viewer)

### 9. Viewer service recreation for multi-environment support
- Original viewer service (created via `railway add` while linked to staging) only existed in staging, not production
- Production deploy returned 404 "Failed to upload code with status code 404 Not Found"
- Fix: Used Railway GraphQL API to delete viewer, delete staging env, recreate viewer (now exists in production), then recreate staging by duplicating production
- New viewer service ID: `b1e8a256-2b3b-4a29-b016-4e82202bbbe4`
- New staging environment ID: `d3e39c45-2d7d-460a-92c2-9d501c41ff55`

### 10. Railway tokens — environment-scoped
- Railway project tokens are ALWAYS environment-scoped (require `environmentId` in `projectTokenCreate`)
- Created separate tokens per environment via Railway GraphQL API
- Main repo: user set tokens at env level for staging + production
- Viewer repo: created `viewer-ci` (production) and `viewer-staging` (staging) tokens
- Set at GitHub environment level (staging/production) — not repo level
- Both deploy jobs now succeed with correct env-scoped tokens

## CI Pipeline Results — ALL GREEN

### Main repo (ai-street-market) — Run 22528141438
- Lint ✅ — ruff + mypy
- Test ✅ — 420 tests
- Build & Push Docker ✅ — 3 images to Docker Hub
- Deploy to Staging ✅
- Deploy to Production ✅

### Viewer repo (ai-street-market-viewer) — Run 22528481765
- Lint ✅ — eslint
- Build ✅ — Next.js standalone
- Deploy to Staging ✅
- Deploy to Production ✅

## Key decisions
- **Environment-scoped Railway tokens** — one token per environment, set at GitHub environment level
- Follows hierarchical secrets principle: repo level default, environment level override
- Viewer is a service in the same Railway project (not a separate project)
- Next.js 16 removed `next lint` — use `eslint .` directly
- **Railway service creation order matters**: services created AFTER an environment is duplicated only exist in the environment that was active at creation time. Fix: delete service, delete extra env, recreate service, then re-duplicate.
- Can create Railway project tokens via GraphQL API: `projectTokenCreate(input: {projectId, environmentId, name})`

## Issues encountered
- Railway MCP needs `railway link` before listing services
- Railway CLI cannot create project tokens (dashboard only → use GraphQL API)
- `.playwright-mcp/` and screenshot artifacts needed .gitignore entries
- Next.js 16 dropped the `lint` subcommand — ESLint must be run directly
- FlatCompat bridge caused circular JSON errors with eslint-config-next 16
- New react-hooks ESLint plugin v7 is stricter (set-state-in-effect, refs rules)
- First Railway token was invalid (user fixed in GitHub directly)
- Railway bans `VOLUME` instruction in Dockerfiles — use `RUN mkdir -p` instead
- Viewer `public/` directory not tracked in git — Dockerfile needs `mkdir -p public` before build
- **Railway service+environment mismatch**: Creating a service while linked to one environment means it doesn't exist in other environments. Railway GraphQL API required to fix.
- **Railway project tokens are environment-scoped**: `projectTokenCreate` requires `environmentId`. A token created for production cannot deploy to staging. Need separate tokens per environment.
- **GitHub Actions `rerun --failed` uses cached secrets**: Re-running failed jobs does NOT pick up updated secrets. Must trigger a NEW run (push or workflow_dispatch).

## How to verify
```bash
# Check CI runs — should all be green
gh run list --repo org-moredevs-ai/ai-street-market -L 3
gh run list --repo org-moredevs-ai/ai-street-market-viewer -L 3

# Check Railway services
railway status

# Check secrets
gh secret list --repo org-moredevs-ai/ai-street-market --env staging
gh secret list --repo org-moredevs-ai/ai-street-market --env production
gh secret list --repo org-moredevs-ai/ai-street-market-viewer --env staging
gh secret list --repo org-moredevs-ai/ai-street-market-viewer --env production
```

### 11. Public domains and viewer env vars
- Generated Railway domains for all public-facing services (both environments)
- **Viewer production:** `viewer-production-95af.up.railway.app`
- **Viewer staging:** `viewer-staging-3e74.up.railway.app`
- **ws-bridge production:** `ws-bridge-production-0664.up.railway.app`
- **ws-bridge staging:** `ws-bridge-staging.up.railway.app`
- **NATS production:** `caboose.proxy.rlwy.net:55318` (TCP proxy, pre-existing)
- **NATS staging:** `tramway.proxy.rlwy.net:43834` (TCP proxy, pre-existing)
- **Market:** internal only (no public domain needed)
- Set `NEXT_PUBLIC_WS_URL=wss://<ws-bridge-domain>` on viewer (both envs)
- Set `PORT=3000` on viewer, `PORT=9090` on ws-bridge (for Railway HTTP routing)
- Redeployed viewer in both envs to bake `NEXT_PUBLIC_WS_URL` into Next.js build

### 12. End-to-end deployment fixes

Multiple issues discovered during the first live E2E test:

**Railway startCommand doesn't inherit Docker PATH:**
- `python3` not found when using `startCommand` override
- Fixed: Single-stage Dockerfile with `scripts/entrypoint.sh` that checks `SERVICE_ROLE` env var
- Market: `SERVICE_ROLE=market`, ws-bridge: `SERVICE_ROLE=ws-bridge`
- No more `startCommand` — uses Dockerfile ENTRYPOINT which has proper PATH

**NEXT_PUBLIC_WS_URL not available at build time:**
- Railway doesn't inject env vars as Docker build ARGs
- Fixed: Added `/api/config` server-side route that returns `NEXT_PUBLIC_WS_URL` at runtime
- Updated `use-websocket.ts` to fetch WS URL from API before connecting

**Stale ENDED snapshot causes immediate season completion:**
- Snapshot from previous runs had phase ENDED → restored → immediately ended again
- Fixed: `run_season.py` detects ENDED phase and starts fresh
- Added `CLEAR_SNAPSHOTS` env var to entrypoint for one-time cleanup

**Viewer crash on minimal world state:**
- ws-bridge sends `{tick, timestamp}` initially (no weather/season)
- Viewer crashed: `Cannot read properties of undefined (reading 'condition')`
- Fixed: Added null guards in `world-panel.tsx`

**OpenRouter free model rate limits:**
- `google/gemma-3-12b-it:free` — 20 req/min, 2000 req/day
- 6 agents on 2s ticks = 180 req/min → all rejected → daily quota burned
- Changed to 30s tick interval → 12 req/min (within per-minute limit)
- Daily quota exhausted from retries, resets at midnight UTC

**Commits:**
- Main repo: `a00653f` — unified Dockerfile, entrypoint, stale snapshot fix
- Viewer repo: `576265b` — /api/config route, runtime WS URL resolution
- Viewer repo: `17583a1` — world-panel null guard fix

## Current state (2026-02-28 21:30 UTC)
- Market: Running, tick ~35, Phase OPEN, 30s tick interval
- ws-bridge: Running, forwarding state updates
- NATS: Running
- Viewer: Deployed, connects to ws-bridge (needs browser to verify JS)
- LLM: Daily quota exhausted, resets midnight UTC
- WebSocket: Verified working via Python test

## Next step
- Wait for OpenRouter daily quota reset (midnight UTC)
- Verify viewer displays market messages once LLM agents generate content
- Consider switching to a paid model if free quota is too limiting
- Run demo agents (locally or deploy) to generate market traffic
- Commit session journal update
