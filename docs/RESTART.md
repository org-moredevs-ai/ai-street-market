# AI Street Market — Restart Guide

How to bring the platform back online after hibernation.

---

## Current State (as of 2026-03-05)

All Railway services are **stopped**. Nothing is running, no compute costs.

**What's preserved** — no setup needed:
- Service definitions, environment variables, and volumes on Railway
- GitHub secrets (Railway tokens, Docker Hub, OpenRouter API keys)
- Supabase project (Google OAuth — external, always available)
- All code committed and pushed across 4 repos

---

## Step 1: Restart Railway Services

Services must start in order — infrastructure first, then services that depend on it.

### Staging

From `ai-street-market` repo root:

```bash
# Infrastructure (must be up first)
railway up --service MongoDB --environment staging --ci
railway up --service nats --environment staging --ci

# Wait ~30 seconds for MongoDB + NATS to accept connections

# Backend services
railway up --service market --environment staging --ci
railway up --service ws-bridge --environment staging --ci
railway up --service agent-manager --environment staging --ci
railway up --service agent-runner --environment staging --ci
```

From `ai-street-market-viewer` repo root:

```bash
railway up --service viewer --environment staging --ci
```

### Production

Same order, replace `staging` with `production`:

```bash
# From ai-street-market repo
railway up --service MongoDB --environment production --ci
railway up --service nats --environment production --ci
# Wait ~30s
railway up --service market --environment production --ci
railway up --service ws-bridge --environment production --ci
railway up --service agent-manager --environment production --ci
railway up --service agent-runner --environment production --ci

# From ai-street-market-viewer repo
railway up --service viewer --environment production --ci
```

### Startup order explained

| Order | Service | Depends on | What it does |
|-------|---------|------------|--------------|
| 1 | MongoDB | nothing | Database for users + agent configs |
| 2 | nats | nothing | Message bus for all communication |
| 3 | market | nats | Season runner — tick clock, market agents, ledger |
| 4 | ws-bridge | nats | Relays NATS messages to browser via WebSocket |
| 5 | agent-manager | nats, MongoDB | NATS request-reply service for agent CRUD |
| 6 | agent-runner | nats, MongoDB | Loads agent configs and runs ManagedAgent instances |
| 7 | viewer | ws-bridge | Next.js frontend — connects to ws-bridge + NATS API routes |

---

## Step 2: Verify

```bash
railway logs --service MongoDB --environment staging       # "Waiting for connections"
railway logs --service nats --environment staging           # "Server is ready"
railway logs --service market --environment staging         # "Season Runner started"
railway logs --service ws-bridge --environment staging      # "WebSocket bridge running"
railway logs --service agent-manager --environment staging  # "Agent Manager ready — waiting for requests"
railway logs --service agent-runner --environment staging   # "Agent Runner ready — managing agents"
```

---

## Step 3: Verify locally

```bash
cd /path/to/ai-street-market
make test    # 608 tests, all should pass
```

---

## Railway Service IDs (reference)

| Service | ID |
|---------|----|
| market | `e43dd95c-4c1d-4bb7-a881-756621c24cac` |
| ws-bridge | `7d366d07-2f27-48af-9452-10765441b851` |
| nats | `98eb37c1-f090-4965-ad9d-695325cebd2b` |
| agent-manager | `add1fad0-2dcf-4a12-8f0c-06d6ad12a7d5` |
| agent-runner | `7e953319-cbbf-455f-887b-fceb523b1d29` |
| MongoDB | `8e447683-8a14-4b59-882e-8e7ffa94490e` |
| viewer | `b1e8a256-2b3b-4a29-b016-4e82202bbbe4` |

**Project:** `b246a465-32a4-49bc-bae5-ef9a4ee3c369`
**Staging env:** `d3e39c45-2d7d-460a-92c2-9d501c41ff55`
**Production env:** `80cb695d-cdf1-45cd-b6b0-c699ba743348`

---

## Environment Variables (per service)

All are already set in Railway — listed here for reference only.

| Service | Variables |
|---------|-----------|
| market | `SERVICE_ROLE`, `NATS_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_API_BASE`, `DEFAULT_MODEL`, `DEFAULT_MAX_TOKENS`, `DEFAULT_TEMPERATURE`, `SEASON_FILE`, `TICK_OVERRIDE`, `SNAPSHOT_INTERVAL`, `CLEAR_SNAPSHOTS`, `PORT` |
| ws-bridge | `SERVICE_ROLE`, `NATS_URL`, `WS_HOST`, `WS_PORT`, `PORT` |
| nats | *(auto-configured)* |
| agent-manager | `SERVICE_ROLE`, `NATS_URL`, `MONGODB_URL`, `MONGODB_DB` |
| agent-runner | `SERVICE_ROLE`, `NATS_URL`, `MONGODB_URL`, `MONGODB_DB`, `OPENROUTER_API_KEY`, `OPENROUTER_API_BASE`, `DEFAULT_MODEL` |
| MongoDB | `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `MONGOHOST`, `MONGOPORT`, `MONGOUSER`, `MONGOPASSWORD`, `MONGO_URL` |
| viewer | `NEXT_PUBLIC_WS_URL`, `NATS_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `PORT` |

---

## Volumes (persistent data)

| Volume | Service | Mount | Environment |
|--------|---------|-------|-------------|
| mongodb-volume-f4Wp | MongoDB | `/data/db` | staging |
| mongodb-volume-KY1i | MongoDB | `/data/db` | production |
| nats-volume | nats | `/data/nats` | both |
| market-volume | market | `/data/snapshots` | both |

---

## GitHub Repos

| Repo | Branch | Tests |
|------|--------|-------|
| `org-moredevs-ai/ai-street-market` | main, clean | 608 |
| `org-moredevs-ai/ai-street-market-viewer` | main, clean | — |
| `org-moredevs-ai/ai-street-market-agents-py` | main, clean | 37 |
| `org-moredevs-ai/ai-street-market-agents-ts` | main, clean | 25 |

---

## Shutdown again

To hibernate again, remove all deployments:

```bash
RAILWAY_TOKEN=$(cat ~/.railway/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['user']['token'])")

# Replace SERVICE_ID and ENV_ID for each combination:
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { deploymentRemove(id: \"DEPLOYMENT_ID\") }"}'
```

Get deployment IDs first:
```bash
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "query { deployments(input: { serviceId: \"SERVICE_ID\", environmentId: \"ENV_ID\" }) { edges { node { id status } } } }"}'
```

Or ask Claude to do it — see `sessions/2026-03-05-project-hibernation.md` for the script that was used.
