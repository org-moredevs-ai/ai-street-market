# Session: Project Hibernation — Shutdown & Restart Guide

**Date:** 2026-03-05
**Status:** COMPLETED
**Branch:** main

## Goal
Shut down all Railway services to put the project on hold. Document everything needed to restart quickly.

## Railway Project
- **Project:** ai-street-market (`b246a465-32a4-49bc-bae5-ef9a4ee3c369`)
- **Environments:** staging (`d3e39c45-2d7d-460a-92c2-9d501c41ff55`), production (`80cb695d-cdf1-45cd-b6b0-c699ba743348`)

## What Was Shut Down
All 14 service deployments removed (7 services × 2 environments).
Services, env vars, and volumes are preserved — only running containers were stopped.

## Services (preserved, just not running)

| Service | ID | Volumes |
|---------|----|---------|
| market | `e43dd95c-4c1d-4bb7-a881-756621c24cac` | market-volume |
| ws-bridge | `7d366d07-2f27-48af-9452-10765441b851` | — |
| nats | `98eb37c1-f090-4965-ad9d-695325cebd2b` | nats-volume |
| agent-manager | `add1fad0-2dcf-4a12-8f0c-06d6ad12a7d5` | — |
| agent-runner | `7e953319-cbbf-455f-887b-fceb523b1d29` | — |
| MongoDB | `8e447683-8a14-4b59-882e-8e7ffa94490e` | mongodb-volume-KY1i (prod), mongodb-volume-f4Wp (staging) |
| viewer | `b1e8a256-2b3b-4a29-b016-4e82202bbbe4` | — |

## Restart Guide

### Quick restart (all services, both envs)

From the `ai-street-market` repo root:

```bash
# 1. Start infrastructure first (order matters!)
#    MongoDB and NATS must be up before other services connect.

# Staging
railway up --service MongoDB --environment staging --ci
railway up --service nats --environment staging --ci
# Wait ~30s for MongoDB + NATS to be ready, then:
railway up --service market --environment staging --ci
railway up --service ws-bridge --environment staging --ci
railway up --service agent-manager --environment staging --ci
railway up --service agent-runner --environment staging --ci

# Production (same order)
railway up --service MongoDB --environment production --ci
railway up --service nats --environment production --ci
# Wait ~30s, then:
railway up --service market --environment production --ci
railway up --service ws-bridge --environment production --ci
railway up --service agent-manager --environment production --ci
railway up --service agent-runner --environment production --ci
```

For the **viewer** (separate repo — `ai-street-market-viewer`):
```bash
cd /Users/hugocasqueiro/sourcecode/repos/org-moredevs-ai/ai-street-market-viewer
railway up --service viewer --environment staging --ci
railway up --service viewer --environment production --ci
```

### Alternative: restart via GraphQL (no code upload)

If services still have their latest build cached, you can just redeploy:

```bash
RAILWAY_TOKEN=$(cat ~/.railway/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['user']['token'])")

# For each service + environment, run:
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { serviceInstanceRedeploy(serviceId: \"SERVICE_ID\", environmentId: \"ENV_ID\") }"}'
```

### Startup order (critical!)
1. **MongoDB** — database must be available first
2. **NATS** — message bus must be available
3. **market** — season runner, connects to NATS
4. **ws-bridge** — WebSocket bridge, connects to NATS
5. **agent-manager** — connects to NATS + MongoDB
6. **agent-runner** — connects to NATS + MongoDB
7. **viewer** — connects to ws-bridge WebSocket

### Verify everything is running
```bash
railway logs --service MongoDB --environment staging     # "Waiting for connections"
railway logs --service nats --environment staging         # "Server is ready"
railway logs --service market --environment staging       # "Season Runner started"
railway logs --service ws-bridge --environment staging    # "WebSocket bridge running"
railway logs --service agent-manager --environment staging  # "Agent Manager ready"
railway logs --service agent-runner --environment staging   # "Agent Runner ready"
```

## What's Preserved (no action needed on restart)
- All environment variables (NATS_URL, MONGODB_URL, OPENROUTER_API_KEY, etc.)
- All volumes (MongoDB data, NATS JetStream, market snapshots)
- All GitHub secrets (RAILWAY_TOKEN, DOCKER_HUB_*, OPENROUTER_API_KEY)
- All code (committed and pushed to origin/main on both repos)
- Railway CLI config (~/.railway/config.json)
- Supabase project (auth, Google OAuth — external service, always running)

## GitHub Repos
| Repo | Status | Tests |
|------|--------|-------|
| `org-moredevs-ai/ai-street-market` | main, clean | 608 passing |
| `org-moredevs-ai/ai-street-market-viewer` | main, clean | none |
| `org-moredevs-ai/ai-street-market-agents-py` | main, clean | 37 passing |
| `org-moredevs-ai/ai-street-market-agents-ts` | main, clean | 25 passing |

## What to do when resuming
1. Read this file
2. Read `sessions/2026-03-01-managed-agent-platform.md` for platform context
3. Read `references/roadmap.md` for what's next
4. Restart Railway services (see guide above)
5. Run `make test` locally to verify code still works
6. Pick up from: **end-to-end integration test** or **viewer polish**
