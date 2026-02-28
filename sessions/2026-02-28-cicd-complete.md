# Session: Complete CI/CD — All Repos, Staging & Production

**Date:** 2026-02-28
**Status:** COMPLETED (code done, commits pending)
**Branch:** main
**Commit:** (pending — nothing committed yet)

## Goal
Replace stub deploy jobs in main repo CI with real Railway CLI commands, create full CI/CD pipeline for the viewer repo (workflow + Dockerfile + standalone config), and create GitHub environments for the viewer repo.

## What was built

### 1. Main repo (`ai-street-market`) — Real Railway deploy jobs
- **Modified** `.github/workflows/ci.yml` — replaced echo-only deploy-staging and deploy-production
- Uses `container: ghcr.io/railwayapp/cli:latest` instead of `npm install -g @railway/cli`
- `railway up --service market --ci` + `railway up --service ws-bridge --ci`
- NATS is NOT deployed from CI (infrastructure, managed via Railway dashboard)

### 2. Viewer repo (`ai-street-market-viewer`) — Full CI/CD pipeline
- **Created** `.github/workflows/ci.yml` — lint → build → deploy-staging → deploy-production
- **Created** `Dockerfile` — multi-stage Next.js standalone (deps → builder → runner, node:22-alpine)
- **Created** `.dockerignore` — excludes node_modules, .next, .git, etc.
- **Modified** `next.config.ts` — added `output: "standalone"` (verified: build produces server.js)

### 3. Viewer repo — GitHub environments
- **Created** `staging` and `production` environments via `gh api`
- No protection rules (requires paid GitHub plan for this repo)

### 4. Railway MCP server
- Installed at user scope: `claude mcp add --scope user Railway npx -- -y @railway/mcp-server`
- Needs: Railway CLI auth (`railway login`) + Claude Code restart

## Verified
- Main repo: 420 tests passing
- Viewer: `next build` succeeds with standalone output (server.js generated)
- GitHub environments exist for both repos

## What's still MISSING (for next session)

### Must do BEFORE pushing:
1. **`railway login`** — run in terminal (browser auth), then restart Claude Code
2. **Verify Railway project** — use Railway MCP to check project, services, environments exist
3. **Viewer `RAILWAY_TOKEN`** — add to staging + production GitHub environments:
   ```bash
   gh secret set RAILWAY_TOKEN --env staging --repo org-moredevs-ai/ai-street-market-viewer
   gh secret set RAILWAY_TOKEN --env production --repo org-moredevs-ai/ai-street-market-viewer
   ```

### Must do to complete:
4. **Commit + push all 4 repos** (all have uncommitted local changes):
   - `ai-street-market` — thoughts feature + CI deploy jobs + session files
   - `ai-street-market-viewer` — CI/CD workflow + Dockerfile + .dockerignore + next.config.ts
   - `ai-street-market-agents-py` — thoughts feature
   - `ai-street-market-agents-ts` — thoughts feature
5. **Verify CI pipelines** — watch GitHub Actions run after push
6. **Railway env vars** — configure in Railway dashboard per service (NATS_URL, OPENROUTER_API_KEY, etc.)

## Key decisions
- Railway CLI container instead of npm install — faster, more reliable
- `railway up` builds from source on Railway (separate from Docker Hub push)
- NATS not deployed from CI — managed as Railway infrastructure
- Next.js standalone output for minimal Docker image
- Node 22 for viewer CI

## Next step
1. Run `railway login` in terminal
2. Restart Claude Code (loads Railway MCP)
3. Use Railway MCP to inspect/verify project state
4. Add viewer RAILWAY_TOKEN secrets
5. Commit and push all repos
