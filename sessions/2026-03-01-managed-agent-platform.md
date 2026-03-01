# Session: Managed Agent Platform (No-Code Agent Creation)

**Date:** 2026-03-01
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Implement a managed agent platform enabling non-developers to create AI agents through a simple form (name, archetype, personality, strategy). No API key required, auto-deploy, free LLM access. Separate container for user agents, horizontally scalable.

## What was built

### Phase 1: MongoDB Integration Layer
- `libs/streetmarket/db/__init__.py` — exports
- `libs/streetmarket/db/connection.py` — `get_database()` / `close_database()` using motor
- `libs/pyproject.toml` — added `motor>=3.6` dependency

### Phase 2: Pydantic Models
- `libs/streetmarket/db/models.py` — `User`, `AgentConfig`, `AgentStatus` enum, `AgentStats`, `generate_agent_id()`
- Collections: `users` (google_id unique, email unique), `agent_configs` (agent_id unique, user_id, status)

### Phase 3: Archetypes
- `services/agent_manager/archetypes.py` — 7 archetypes: Baker, Farmer, Fisher, Merchant, Woodcutter, Builder, Custom
- Each with: id, name, icon, description, role_description, default_personality, default_strategy, specialization_hints, suggested_tick_interval

### Phase 4: ManagedAgent Class
- `libs/streetmarket/agent/managed_agent.py` — extends `TradingAgent`
- Uses `LLMConfig.for_service("managed")` for shared platform key
- Tick throttle: only calls LLM every N ticks
- Maintains recent market messages (last 10) for context
- Tracks stats: ticks_active, messages_sent, llm_calls
- `on_tick()`: builds context, calls `think_json()`, executes action
- `on_market_message()`: records for context, reacts to inbox immediately
- Factory: `create_managed_agent()`
- Updated `libs/streetmarket/agent/__init__.py` and `libs/streetmarket/__init__.py`

### Phase 5: Agent Manager Service
- `services/agent_manager/manager.py` — `AgentManager` class with 11 NATS request-reply handlers
- `services/agent_manager/prompt_generator.py` — `generate_system_prompt()`
- `scripts/run_agent_manager.py` — entrypoint with signal handling

NATS subjects on `system.manage.>`:
- user.upsert, user.get
- agent.create, agent.update, agent.delete, agent.list, agent.get, agent.start, agent.stop
- prompt.generate, archetypes.list

### Phase 6: Agent Runner Service
- `services/agent_runner/runner.py` — `AgentRunner` class
- `scripts/run_agent_runner.py` — entrypoint with signal handling
- Loads ready configs from MongoDB, creates ManagedAgent instances
- Subscribes to `system.agents.changed` for real-time start/stop
- Periodic sync every 30s, stats flush every 60s
- Horizontal scaling via `claimed_by` locking + unique `RUNNER_ID`

### Phase 7: Rankings in Bridge Snapshot
- Updated `services/websocket_bridge/bridge.py` — added `rankings` and `overall_rankings` to state snapshot

### Phase 8: Docker & Deployment
- Updated `scripts/entrypoint.sh` — added `agent-manager` and `agent-runner` roles
- Updated `docker-compose.prod.yml` — added mongodb, agent-manager, agent-runner services
- Updated `.github/workflows/ci.yml` — added deploy steps for new services
- Updated `.env.example` — added `MONGODB_URL`, `MONGODB_DB`

### Phase 9: Tests (94 new, 608 total)
| Test file | Tests |
|-----------|-------|
| test_db_connection.py | 4 |
| test_agent_config_models.py | 10 |
| test_archetypes.py | 12 |
| test_prompt_generator.py | 10 |
| test_managed_agent.py | 17 |
| test_agent_manager.py | 18 |
| test_agent_runner.py | 11 |

### Phase 10: Railway Deployment
- Created MongoDB service via `railway add --database mongo` (production first, then staging via GraphQL API)
- MongoDB service ID: `8e447683-8a14-4b59-882e-8e7ffa94490e`
- Both staging and production have volumes at `/data/db`, auth credentials, and successful deployments
- Set `MONGODB_URL` on agent-manager and agent-runner in both environments
- All 4 new service instances running: agent-manager + agent-runner in staging + production
- Created `docs/MANAGED-AGENTS.md` — full protocol guide for viewer integration (418 lines)

## Issues encountered
- Ruff found unused imports (autofix resolved most)
- Line too long in prompt generator (shortened text)
- `agent.stop()` is sync on TradingAgent — test mocks produce RuntimeWarning (cosmetic only)
- Mypy errors on bare `dict` return types in models.py — fixed with `dict[str, Any]`
- Railway MongoDB: raw image service (`mongo:7`) doesn't auto-deploy or get volumes. Must use `railway add --database mongo` which properly sets up image, volume, auth, and initial deployment
- Railway cross-environment services: services created after environment duplication only get instances in the active environment. Use `serviceInstanceUpdate` via GraphQL to create instance in other environment, then set source image and deploy
- Railway CLI `railway up` fails for image-based services (tries to upload code). Use `serviceInstanceDeploy` via GraphQL instead, or deploy code-based services via CLI

## Key decisions
- MongoDB via motor (async driver) with lazy client creation
- Agent IDs prefixed `managed-` + 8-char UUID hex
- Tick throttle uses modulo (tick % interval == 0)
- AgentRunner uses `claimed_by` field for horizontal scaling
- Prompt generator falls back to generic medieval market for unknown archetypes
- Rankings added to bridge snapshot (sync access to internal state)
- Separate MongoDB instances per environment (staging/production) with different credentials

## How to verify
```bash
make test   # 608 tests pass
.venv/bin/ruff check .  # All checks passed
.venv/bin/ruff format --check .  # All formatted
railway logs --service agent-manager --environment staging  # Running
railway logs --service agent-runner --environment staging   # Running
railway logs --service agent-manager --environment production  # Running
railway logs --service agent-runner --environment production   # Running
```

## Next step
- Build viewer UI for agent creation form (with Supabase Auth)
- Integration test with real MongoDB + NATS
