# Session: Railway Setup, Secrets, and Push All Repos

**Date:** 2026-02-28
**Status:** IN_PROGRESS
**Branch:** main
**Commit:** (pending)

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
- **Main repo**: RAILWAY_TOKEN at repo level, OPENROUTER_API_KEY at env level
- **Viewer repo**: RAILWAY_TOKEN at repo level
- Both repos: DOCKER_HUB_USERNAME + DOCKER_HUB_TOKEN at repo level (main only)

### 6. Viewer .gitignore updated
- Added `.playwright-mcp/` and `*.png` to ignore

### 7. Agents repos
- Python agents: already committed and pushed (thoughts feature)
- TypeScript agents: already committed and pushed (thoughts feature)

## Key decisions
- **Project-level Railway token** + `--environment` flag instead of env-scoped tokens
- Follows hierarchical secrets principle: repo level default, environment level override
- Viewer is a service in the same Railway project (not a separate project)

## Issues encountered
- Railway MCP needs `railway link` before listing services
- Railway CLI cannot create project tokens (dashboard only)
- `.playwright-mcp/` and screenshot artifacts needed .gitignore entries

## How to verify
```bash
# Check Railway
railway status
railway service status

# Check GitHub secrets
gh secret list --repo org-moredevs-ai/ai-street-market
gh secret list --repo org-moredevs-ai/ai-street-market-viewer

# Check CI runs
gh run list --repo org-moredevs-ai/ai-street-market -L 3
gh run list --repo org-moredevs-ai/ai-street-market-viewer -L 3
```

## Next step
- Monitor CI pipeline runs after push
- Configure viewer env vars on Railway (NEXT_PUBLIC_WS_URL, etc.)
- First actual deployment to Railway
