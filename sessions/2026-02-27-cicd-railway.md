# Session: CI/CD Pipeline — Railway Deployment with Persistence

**Date:** 2026-02-27
**Status:** COMPLETED
**Branch:** main
**Commit:** (fill when done)

## Goal
Add state persistence (periodic snapshots + recovery), containerize services (Docker), set up CI/CD (GitHub Actions), prepare for Railway deployment (staging + production), and document the deployment architecture.

## What was built

### Step 1: State Persistence
- `libs/streetmarket/persistence/__init__.py` — package init
- `libs/streetmarket/persistence/snapshots.py` — StateSnapshot class (save/restore/apply)
- `tests/test_snapshots.py` — round-trip tests

### Step 2: Snapshot Integration
- Modified `scripts/run_season.py` — `--snapshot-dir`, `--snapshot-interval`, restore on startup, periodic saves

### Step 3: Standalone Bridge
- `scripts/run_bridge.py` — standalone WS bridge entry point
- `tests/test_run_bridge.py` — bridge args tests

### Step 4: Docker Infrastructure
- `Dockerfile` — multi-stage (base, market, ws-bridge)
- `infrastructure/Dockerfile.nats` — NATS with prod config
- `infrastructure/nats/nats-server.prod.conf` — production NATS config
- `docker-compose.prod.yml` — 3-service orchestration
- `.dockerignore` — exclude dev files
- `scripts/entrypoint-market.sh` — env-var driven market entrypoint
- `scripts/entrypoint-bridge.sh` — env-var driven bridge entrypoint

### Step 5: CI/CD Pipeline
- `.github/workflows/ci.yml` — lint, test, build, deploy-staging, deploy-production

### Step 6: Documentation
- `docs/DEPLOYMENT.md` — deployment architecture, env vars, setup instructions

## Issues encountered
- Import sorting: `streetmarket.persistence` needed alphabetical placement between `models` and `policy`
- Unused imports in test files needed cleanup
- Ruff format differences in tuple return type annotations and list formatting

## Key decisions
- Multi-stage Dockerfile with shared base layer
- Snapshots as JSON files with last-3 retention
- Railway deployment with manual approval gates
- Docker Hub for image registry (hugocasqueiromoredevsai)

## How to verify
```bash
python -m pytest tests/ -x -q
docker build --target market -t streetmarket-market .
docker build --target ws-bridge -t streetmarket-ws-bridge .
docker build -f infrastructure/Dockerfile.nats -t streetmarket-nats infrastructure/
```

## Next step
- Set up GitHub environments (staging/production) with secrets
- Create Railway project with 3 services + volumes
- Set up external agent repos
