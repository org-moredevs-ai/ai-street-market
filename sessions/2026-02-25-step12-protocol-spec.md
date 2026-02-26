# Session: Step 12 — Protocol Specification + Agent Templates

**Date:** 2026-02-25
**Status:** COMPLETED
**Branch:** main
**Commit:** (fill when done)

## Goal
Create the protocol specification, agent templates, and getting-started guide that enables external developers to build agents for the AI Street Market without reading source code.

Three deliverables:
1. `docs/PROTOCOL.md` — authoritative protocol specification
2. `templates/python-agent/` and `templates/typescript-agent/` — minimal starter agents
3. `docs/BUILDING_AN_AGENT.md` — tutorial walkthrough

Plus updates to `CLAUDE.md` and `README.md`.

## What was built

### Phase 1: Protocol Specification (`docs/PROTOCOL.md`)
- Complete protocol spec covering: overview, connection, envelope format, topics, all 21 message types, agent lifecycle, economy rules, catalogue, validation rules, example message flows

### Phase 2: Python Agent Template (`templates/python-agent/`)
- Minimal agent using the `streetmarket` SDK
- Hardcoded potato gatherer/seller strategy (no LLM)
- Files: agent.py, strategy.py, __main__.py, requirements.txt, .env.example, README.md

### Phase 3: TypeScript Agent Template (`templates/typescript-agent/`)
- Standalone agent — no Python SDK dependency
- Same potato gatherer/seller strategy
- Files: src/protocol.ts, src/state.ts, src/strategy.ts, src/index.ts, package.json, tsconfig.json, .env.example, README.md

### Phase 4: Getting Started Guide (`docs/BUILDING_AN_AGENT.md`)
- Tutorial walkthrough from prerequisites to running your first agent

### Phase 5: Documentation Updates
- `CLAUDE.md` — Agent Isolation principle, updated project structure
- `README.md` — Build Your Own Agent section, updated stats

## Issues encountered
No issues — clean implementation. All source files were read and protocol documented from actual code.

## Key decisions
- Templates use hardcoded strategies (no LLM) — simplest viable economy participant
- Python template uses SDK (happy path), TypeScript is standalone (proves protocol-level participation)
- Both templates implement identical potato gathering + selling strategy for direct comparison

## How to verify
```bash
make test  # Existing tests still pass
# Templates are standalone — verified by inspection of code correctness against protocol
```

## Next step
Step 13: Viewer UX, paid model demo, action queuing, agent memory
