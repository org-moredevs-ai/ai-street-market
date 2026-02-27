# Deployment Architecture

## Overview

The AI Street Market runs as 3 containerized services on Railway, with external agents and a viewer connecting over the internet.

```
                              INTERNET
                                 |
         +-----------+-----------+-----------+-----------+
         |           |           |           |           |
  +------v------+ +--v---+ +----v-----+ +---v--------+  |
  | viewer      | | NATS | | ws-bridge| | agents-py  |  |
  | :3000       | | :4222| | :9090    | | agents-ts  |  |
  | (frontend)  | | (NKey| | (WS      | | (external) |  |
  | static/SSR  | | auth)| |  relay)  | | trading    |  |
  +------+------+ +--+---+ +----+-----+ +---+--------+  |
         |            |          |           |            |
         |   RAILWAY PRIVATE NETWORKING      |            |
         |   nats.railway.internal:4222      |            |
         |            |          |           |            |
         |   +--------v----------v-----------+            |
         |   |          NATS :4222                        |
         |   |   JetStream + persistent volume            |
         |   |   subjects: market.> system.> agent.>      |
         |   +--------+---------------------------------+ |
         |            |                                   |
         |   +--------v---------------------------------+ |
         |   |         market (season runner)            | |
         |   | Governor, Banker, Nature, Meteo,          | |
         |   | Landlord, Town Crier + Tick Clock         | |
         |   | + periodic state snapshots to /data/      | |
         |   +-----------------------------------------+ |
         |                                                |
         +-- connects to ws-bridge via public WebSocket --+
```

## Services

### 4 Repos, 4 CI/CD Pipelines

| Repo | Railway Service(s) | Description |
|------|-------------------|-------------|
| `ai-street-market` (this) | `nats`, `market`, `ws-bridge` | Core infrastructure |
| `ai-street-market-viewer` | `viewer` | Frontend UI |
| `ai-street-market-agents-py` | External | Python trading agents |
| `ai-street-market-agents-ts` | External | TypeScript trading agents |

### Network Access

| Service | Port | Access | Auth |
|---------|------|--------|------|
| `viewer` | 3000 | Public (browser) | None (static UI) |
| `ws-bridge` | 9090 | Public (WebSocket) | None (read-only relay) |
| `NATS` | 4222 | Public (agents) | NKey auth (production) |
| `market` | -- | Private only | Internal to Railway |

### Internal Networking

Market and ws-bridge connect to NATS via Railway private networking (`nats.railway.internal:4222`). External agents connect to the public NATS URL.

## Docker Images

All images are published to Docker Hub under `hugocasqueiromoredevsai/`:

| Image | Source | Target |
|-------|--------|--------|
| `streetmarket-market` | `Dockerfile` (target: market) | Season runner + 6 market agents |
| `streetmarket-ws-bridge` | `Dockerfile` (target: ws-bridge) | WebSocket relay |
| `streetmarket-nats` | `infrastructure/Dockerfile.nats` | NATS with prod config |

### Building Locally

```bash
# Market service
docker build --target market -t streetmarket-market .

# WebSocket bridge
docker build --target ws-bridge -t streetmarket-ws-bridge .

# NATS
docker build -f infrastructure/Dockerfile.nats -t streetmarket-nats infrastructure/
```

### Running Locally (Production-like)

```bash
OPENROUTER_API_KEY=sk-or-xxx DEFAULT_MODEL=google/gemma-3-12b-it:free \
  docker compose -f docker-compose.prod.yml up
```

## Environment Variables

### Market Service

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NATS_URL` | No | `nats://localhost:4222` | NATS connection URL |
| `SEASON_FILE` | No | `season-1.yaml` | Season config filename |
| `TICK_OVERRIDE` | No | *(none)* | Override tick interval (seconds) |
| `SNAPSHOT_DIR` | No | `/data/snapshots` | State snapshot directory |
| `SNAPSHOT_INTERVAL` | No | `50` | Save snapshot every N ticks |
| `OPENROUTER_API_KEY` | **Yes** | -- | OpenRouter API key for LLM |
| `OPENROUTER_API_BASE` | No | `https://openrouter.ai/api/v1` | OpenRouter base URL |
| `DEFAULT_MODEL` | **Yes** | -- | LLM model identifier |
| `DEFAULT_MAX_TOKENS` | No | `400` | Max tokens per LLM call |
| `DEFAULT_TEMPERATURE` | No | `0.7` | LLM temperature |

### WebSocket Bridge

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NATS_URL` | No | `nats://localhost:4222` | NATS connection URL |
| `WS_HOST` | No | `0.0.0.0` | WebSocket bind host |
| `WS_PORT` | No | `9090` | WebSocket port |

### NATS

NATS configuration is baked into the Docker image via `nats-server.prod.conf`. JetStream data is persisted to a Railway volume at `/data/jetstream`.

## State Persistence

### Snapshots

The market service periodically saves state snapshots to `/data/snapshots/`:

- **Format:** `snapshot-tick-{N}.json` (JSON)
- **Interval:** Every N ticks (configurable via `SNAPSHOT_INTERVAL`)
- **Retention:** Keeps last 3 snapshots, deletes older ones
- **On startup:** Automatically restores from the latest snapshot if one exists
- **On shutdown:** Saves a final snapshot

**What's preserved:**
- Ledger: wallets, inventory (with batches), transactions
- Registry: all agent records, profiles, death info
- World state: fields, buildings, resources, weather, properties
- Season: phase, current tick, phase timestamps
- Ranking: community contribution scores

### JetStream

NATS JetStream data is persisted to a Railway volume at `/data/jetstream`. Messages survive NATS restarts.

### Disaster Recovery

1. State snapshots are stored on a persistent volume
2. On crash/restart, the market service finds the latest snapshot and restores
3. NATS purge is skipped when restoring from a snapshot
4. Season phase and tick are restored exactly

## CI/CD Pipeline

### Workflow: `.github/workflows/ci.yml`

```
Push to main/develop
     |
     +---> [lint]     ruff check, ruff format --check, mypy     (parallel)
     +---> [test]     pytest 397+ tests                         (parallel)
     |
     +---> Both pass?
              |
              +---> [build]   Docker build+push 3 images        (push only)
                       |
                       +---> [deploy-staging]   MANUAL APPROVAL
                                |
                                +---> [deploy-production]   MANUAL APPROVAL (main only)
```

- **PRs:** Only lint + test. No build, no deploy.
- **Push to develop:** Lint + test + build + deploy-staging (manual gate).
- **Push to main:** Full pipeline through production (two manual gates).

### GitHub Repository Secrets

| Secret | Purpose |
|--------|---------|
| `DOCKER_HUB_USERNAME` | `hugocasqueiromoredevsai` |
| `DOCKER_HUB_TOKEN` | Docker Hub access token |

### GitHub Environment: `staging`

**Protection rules:** Required reviewers (1), allowed branches: main, develop

| Type | Name | Value |
|------|------|-------|
| Secret | `RAILWAY_TOKEN` | Railway project token |
| Secret | `OPENROUTER_API_KEY` | OpenRouter API key |
| Variable | `OPENROUTER_API_BASE` | `https://openrouter.ai/api/v1` |
| Variable | `DEFAULT_MODEL` | `google/gemma-3-12b-it:free` |
| Variable | `DEFAULT_MAX_TOKENS` | `400` |
| Variable | `DEFAULT_TEMPERATURE` | `0.7` |
| Variable | `SEASON_FILE` | `season-1.yaml` |
| Variable | `TICK_OVERRIDE` | `2` (fast ticks for testing) |

### GitHub Environment: `production`

**Protection rules:** Required reviewers (1), allowed branches: main only

Same variables as staging, except:
- `TICK_OVERRIDE` = *(empty, real speed from season YAML)*
- `DEFAULT_MODEL` = *(potentially paid model)*
- Own `RAILWAY_TOKEN` and `OPENROUTER_API_KEY`

## Railway Setup

### 1. Create Railway Project

Create a new project with 3 services:

1. **nats** — Docker image `hugocasqueiromoredevsai/streetmarket-nats:latest`
   - Add persistent volume at `/data/jetstream`
   - Expose port 4222 (public, for external agents)
   - Expose port 8222 (internal, monitoring)

2. **market** — Docker image `hugocasqueiromoredevsai/streetmarket-market:latest`
   - Add persistent volume at `/data/snapshots`
   - Set environment variables (see table above)
   - No public port (internal only)
   - Set `NATS_URL=nats://nats.railway.internal:4222`

3. **ws-bridge** — Docker image `hugocasqueiromoredevsai/streetmarket-ws-bridge:latest`
   - Expose port 9090 (public, for viewer)
   - Set `NATS_URL=nats://nats.railway.internal:4222`

### 2. Configure Networking

- Enable Railway private networking for internal service communication
- Market and ws-bridge use `nats.railway.internal:4222`
- External agents use the public NATS URL

### 3. Deploy

Push to main to trigger the CI/CD pipeline, or deploy manually via Railway dashboard.

## Viewer Connection

The viewer (separate repo) connects to the ws-bridge via public WebSocket URL:

```
ws://<ws-bridge-public-url>:9090
```

**Protocol (server to client):**

```json
{"type": "message", "data": {envelope}}     // Live NL message
{"type": "state",   "data": {snapshot}}      // World state snapshot
{"type": "history", "data": [messages]}      // Recent messages on connect
```

The viewer is read-only — it cannot publish messages to NATS.
