# Session: Railway Setup, Secrets, and Push All Repos

**Date:** 2026-02-28
**Status:** IN_PROGRESS
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

## CI Pipeline Results

### Main repo (ai-street-market)
- Lint ✅ (33s) — ruff + mypy
- Test ✅ (27s) — 420 tests
- Build & Push Docker ✅ (1m25s) — 3 images to Docker Hub
- Deploy to Staging — WAITING (needs environment approval from hc-moredevs-ai)

### Viewer repo (ai-street-market-viewer)
- Lint ✅ (26s) — eslint
- Build ✅ (30s) — Next.js standalone
- Deploy to Staging — RERUNNING (first attempt had invalid token, user fixed it)

## Key decisions
- **Project-level Railway token** + `--environment` flag instead of env-scoped tokens
- Follows hierarchical secrets principle: repo level default, environment level override
- Viewer is a service in the same Railway project (not a separate project)
- Next.js 16 removed `next lint` — use `eslint .` directly

## Issues encountered
- Railway MCP needs `railway link` before listing services
- Railway CLI cannot create project tokens (dashboard only)
- `.playwright-mcp/` and screenshot artifacts needed .gitignore entries
- Next.js 16 dropped the `lint` subcommand — ESLint must be run directly
- FlatCompat bridge caused circular JSON errors with eslint-config-next 16
- New react-hooks ESLint plugin v7 is stricter (set-state-in-effect, refs rules)
- First Railway token was invalid (user fixed in GitHub directly)

## How to verify
```bash
# Check CI runs
gh run list --repo org-moredevs-ai/ai-street-market -L 3
gh run list --repo org-moredevs-ai/ai-street-market-viewer -L 3

# Check GitHub secrets
gh secret list --repo org-moredevs-ai/ai-street-market
gh secret list --repo org-moredevs-ai/ai-street-market-viewer

# Check Railway
railway status
railway service status
```

## Next step
- Approve staging deploy in GitHub (main repo waiting for reviewer approval)
- Verify viewer deploy succeeds with fixed token
- Configure viewer env vars on Railway (NEXT_PUBLIC_WS_URL pointing to ws-bridge)
- Generate public domains for services on Railway
- Test end-to-end: NATS → market agents → ws-bridge → viewer
