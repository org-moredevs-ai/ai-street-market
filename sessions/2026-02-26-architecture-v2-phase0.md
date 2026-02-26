# Session: Architecture v2 — Phase 0 (Foundation Design)

**Date:** 2026-02-26
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending — ready for commit)

## Goal
Execute Phase 0 of the Architecture v2 redesign:
- Branch current code to `v1-archive` (preserve v1)
- Persist architecture design as reference documents
- Define policy schema (world + season YAML)
- Define protocol v2 (pure NL envelope, topics, ledger events)
- Define world state schema
- Update CLAUDE.md and roadmap for v2
- Clean main — remove discarded v1 code, keep infrastructure

## Context
After thorough analysis of both repos, a critical realization: the current codebase implements a game engine with fixed rules, not a living economy of communicating LLM agents. The v2 architecture shifts to:
- Pure natural language communication between ALL agents
- Two layers: deterministic infrastructure + LLM agent intelligence
- No hardcoded catalogue, recipes, or programmatic validation
- Season system with UTC-based timing
- External agent repos (separate public repos per language stack)
- NATS NKey authentication + topic permissions

## What was built

### Phase 0.1: Preservation
- [x] 0.1.1 Create v1-archive branch and push to origin
- [x] 0.1.2 Return to main

### Phase 0.2: Architecture Documentation
- [x] 0.2.1 Create references/architecture-v2.md (full design doc)
- [x] 0.2.2 Create docs/PROTOCOL-V2.md (NL envelope, topics, ledger events, examples)
- [x] 0.2.3 Create docs/WORLD-STATE.md (world state schema, interfaces)

### Phase 0.3: Policy Schema
- [x] 0.3.1 Create policies/earth-medieval-temperate.yaml (world policy — medieval market town with 6 regions, crops, animals, crafting, energy, weather)
- [x] 0.3.2 Create policies/season-1.yaml (Season 1 "Harvest Festival" — timing, biases, winning criteria, awards, character personalities)

### Phase 0.4: Project Updates
- [x] 0.4.1 Update CLAUDE.md for v2 (new architecture, protocol, topics, project structure)
- [x] 0.4.2 Update references/roadmap.md for v2 (new build order: Phase 0-5 + future)
- [x] 0.4.3 Update README.md for v2
- [x] 0.4.4 Update pyproject.toml (version 2.0.0, added pyyaml, removed unused deps)
- [x] 0.4.5 Update Makefile (removed v1 service/agent targets)
- [x] 0.4.6 Fix .gitignore (un-ignore references/, remove lumberjack-specific entries)

### Phase 0.5: Code Cleanup
- [x] 0.5.1 Remove agents/ (entire directory — moves to separate repos)
- [x] 0.5.2 Remove templates/ (entire directory — moves to agent repos)
- [x] 0.5.3 Remove services/governor/, banker/, world/, town_crier/, websocket_bridge/
- [x] 0.5.4 Remove v1 models: catalogue.py, energy.py, rent.py, messages.py
- [x] 0.5.5 Remove v1 helpers: validation.py, topic_map.py
- [x] 0.5.6 Remove v1 agent SDK: actions.py, base.py, state.py
- [x] 0.5.7 Remove v1 scripts: proof_of_life.py, run_economy.py
- [x] 0.5.8 Remove v1 docs: PROTOCOL.md, BUILDING_AN_AGENT.md
- [x] 0.5.9 Remove v1 reference backup: roadmap-v2-backup-2026-02-24.md
- [x] 0.5.10 Remove all v1 test files (46 files)
- [x] 0.5.11 Rewrite envelope.py for v2 (message field, no type/payload)
- [x] 0.5.12 Rewrite topics.py for v2 (simplified streets)
- [x] 0.5.13 Rewrite factory.py for v2 (NL message creation)
- [x] 0.5.14 Strip llm_brain.py to extract_json utility only
- [x] 0.5.15 Clean llm_config.py (remove v1 AGENT_PREFIXES)
- [x] 0.5.16 Update all __init__.py files for v2 exports
- [x] 0.5.17 Reinstall library and verify all imports work

### Phase 0.6: Memory
- [x] 0.6.1 Update MEMORY.md for v2 transition

## Issues encountered
1. `.gitignore` had `references/` excluded — architecture docs wouldn't have been committed. Fixed by removing that entry.
2. The `libs/streetmarket/agent/llm_brain.py` had deep v1 dependencies (ActionKind, AgentState, catalogue, energy costs). Stripped to just `extract_json()` — the universally reusable utility.
3. `libs/streetmarket/helpers/topic_map.py` depended entirely on catalogue — removed completely.
4. `libs/streetmarket/helpers/factory.py` depended on MessageType enums — rewrote for v2 NL messages.

## Key decisions
1. v1-archive preserves ALL current code — safe to delete from main
2. Architecture document is self-contained — single source of truth for v2
3. Policy YAML defines the WORLD, not the RULES — LLM agents interpret policies
4. Protocol v2 envelope has `message` field (NL string), no `type`/`payload`
5. Ledger events are internal (invisible to trading agents)
6. Kept `extract_json()` and `LLMConfig` — universally reusable patterns
7. Kept NATS client unchanged — it only depends on Envelope + topic conversion
8. Version bumped to 2.0.0 in pyproject.toml
9. Added `pyyaml` dependency for policy loading

## How to verify
```bash
# v1-archive branch exists
git branch -a | grep v1-archive

# Architecture docs exist
ls references/architecture-v2.md docs/PROTOCOL-V2.md docs/WORLD-STATE.md

# Policy YAMLs parse correctly
source .venv/bin/activate
python -c "import yaml; d=yaml.safe_load(open('policies/earth-medieval-temperate.yaml')); print(d['world']['name'])"
python -c "import yaml; d=yaml.safe_load(open('policies/season-1.yaml')); print(d['season']['name'])"

# Library imports work
python -c "from streetmarket import Envelope, Topics, MarketBusClient, LLMConfig, extract_json, create_message, parse_message; print('OK')"

# v1 code removed
test ! -f libs/streetmarket/models/catalogue.py && echo 'No catalogue'
test ! -f services/governor/rules.py && echo 'No governor rules'
test ! -d agents && echo 'No agents dir'
```

## Next step
Phase 1 — New Foundation:
- NATS NKey auth + topic permissions
- Deterministic ledger (wallets, inventory — interface-based)
- World state store (fields, buildings, weather, ownership)
- Policy engine (load YAML, inject into LLM prompts)
- Agent registry v2 (onboarding, profiles, visibility)
- Season manager (UTC dates -> ticks, phase lifecycle)
- Ranking engine (per-season + overall)
- Tick clock (UTC-aware, configurable interval)
- New test framework
