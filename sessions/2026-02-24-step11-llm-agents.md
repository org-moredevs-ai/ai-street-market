# Session: Step 11 — LLM-Driven Agents + Economy Smoke Test

**Date:** 2026-02-24
**Status:** COMPLETED
**Branch:** main
**Commit:** e52758c (main Step 11), plus follow-up fixes

## Goal
Make the AI Street Market actually AI-driven:
1. LLM brains for ALL agents via LangChain/LangGraph + OpenRouter
2. LLM-ON by default for Town Crier and World Nature (remove toggles)
3. AI-mandatory guardrail tests + CLAUDE.md rule
4. Economy smoke test to catch trading/timing bugs

## What was built

### Phase 1: Dependencies + Agent SDK
- Added `langgraph`, `langchain-openai`, `langchain-core` to pyproject.toml
- Created `libs/streetmarket/agent/llm_config.py` — LLM configuration loader (env vars, zero hardcoded)
- Created `libs/streetmarket/agent/llm_brain.py` — shared LLM brain (~250 lines)
  - `AgentAction` + `ActionPlan` Pydantic schemas for structured output
  - `MARKET_RULES` system prompt (~800 tokens) — economy rules, items, recipes, actions
  - `serialize_state()` — human-readable agent state for LLM
  - `validate_action()` + `validate_plan()` — validates LLM output against current state
  - `AgentLLMBrain` class — decide() calls LLM via OpenRouter, validates, returns actions
- Made `decide()` async in TradingAgent base class
- Updated agent SDK exports (`AgentLLMBrain`, `LLMConfig`)

### Phase 2: Python Agents (Farmer, Chef, Baker, Mason, Builder)
- Added PERSONA constants to all 5 strategy files (personality + strategy tips)
- Renamed `decide` → `decide_hardcoded` in all strategies (test fixtures only)
- Integrated LLM brain into all 5 agent.py files
  - Each agent creates `AgentLLMBrain(self.AGENT_ID, PERSONA)` in `__init__`
  - `decide()` delegates to `self._brain.decide(state)`

### Phase 3: Services Migration
- Migrated Town Crier narrator to LangChain/OpenRouter
  - Removed `TOWN_CRIER_USE_LLM` toggle, `enabled` flag, direct anthropic SDK usage
  - Added `NarrationSchema` Pydantic model for structured output
  - Uses `LLMConfig.for_service("town_crier")` + `ChatOpenAI` + `with_structured_output`
- Migrated World Nature to LangChain/OpenRouter
  - Removed `WORLD_USE_LLM_NATURE` toggle, direct anthropic SDK usage
  - Added `NatureOutputSchema` + `NatureEventSchema` Pydantic models
  - Uses `LLMConfig.for_service("world")` + `ChatOpenAI` + `with_structured_output`

### Phase 4: TypeScript Lumberjack
- Added `@langchain/openai`, `@langchain/core`, `zod` dependencies
- Created `agents/lumberjack/src/llm_brain.ts` (~300 lines)
  - `LLMConfig` + `loadConfig()` — env var configuration
  - `LUMBERJACK_PERSONA` — personality for the lumberjack
  - `serializeState()` — state to text for LLM
  - `validateAction()` + `validatePlan()` — action validation
  - `LumberjackLLMBrain` class — mirrors Python pattern
- Renamed `decide` → `decideHardcoded` in strategy.ts
- Updated `index.ts` to use LLM brain
- Created `llm_brain.test.ts` (28 tests)

### Phase 5: Config + Tests
- Updated `.env.example` for OpenRouter (removed ANTHROPIC_API_KEY, toggles)
- Added AI-Mandatory Rule to `CLAUDE.md`
- Added `smoke-test` target to Makefile
- Required `OPENROUTER_API_KEY` in `scripts/run_economy.py` (fail-fast)
- Created `tests/test_ai_guardrails.py` (10 tests) — architecture enforcement
- Created `tests/test_agent_llm_brain.py` (40 tests) — LLM brain unit tests
- Created `tests/test_economy_smoke.py` (8 tests) — integration smoke test
- Updated `tests/test_narrator.py` — LangChain mocking pattern
- Updated `tests/test_nature_brain.py` — LangChain mocking pattern
- Updated all 5 strategy test files — `decide_hardcoded as decide`
- Updated `tests/test_economy_integration.py` — mock LLM brain with hardcoded strategies

## Issues encountered

1. **Energy check lookup** — `validate_action()` used `kind_str.upper()` but `ACTION_ENERGY_COSTS` keys are lowercase. Fixed: use `kind_str` without `.upper()`.

2. **Integration test NATS pollution** — Running economy on the same NATS server causes integration tests to fail due to state pollution (messages from tick 700+ interfering with test expectations). These are pre-existing issues, not caused by Step 11. Integration tests pass in a clean NATS environment.

3. **Async decide() in integration tests** — After making `decide()` async, the economy integration tests needed async wrappers around the hardcoded strategies for LLM mocking.

4. **World Engine tick loop crash** — `services/world/world.py:115` referenced `self._nature.enabled` which was removed when LLM toggles were eliminated. The AttributeError silently killed the tick loop. Fixed: `elif self._nature.enabled:` → `else:`.

5. **`with_structured_output` incompatible with many OpenRouter models** — nemotron and other models don't support function calling, which `with_structured_output` requires. Replaced with raw LLM call + `extract_json()` utility that parses JSON from any text format (code blocks, embedded in text, etc.). All 3 files updated: llm_brain.py, narrator.py, nature.py.

6. **nemotron model returns empty responses ~60% of the time** — A model reliability issue, not a code bug. The economy handles this gracefully (agents skip ticks). Need to switch to a more reliable model for production.

## Key decisions
- OpenRouter as unified LLM gateway (OpenAI-compatible API via `ChatOpenAI`)
- ~~`with_structured_output(ActionPlan)` for guaranteed valid Pydantic output~~ → Replaced with raw LLM + manual JSON extraction (works with ALL models)
- Agent skips tick on LLM failure (no hardcoded fallback at runtime)
- Default model: `nvidia/nemotron-nano-12b-v2-vl:free` (free tier for dev)
- Per-agent model override via env vars (FARMER_MODEL, etc.)
- `LLMConfig.for_agent()` and `LLMConfig.for_service()` for configuration
- `extract_json()` utility handles: pure JSON, markdown code blocks, JSON embedded in text

## Test Results
- **876 Python unit tests pass** (no API key needed)
- **50 TypeScript tests pass** (22 strategy + 28 LLM brain)
- **903 total Python tests** (including 27 integration tests)
- **953 total tests** (Python + TypeScript)
- Integration tests affected by NATS state pollution (pre-existing)

## How to verify
```bash
# Unit tests (no API key needed)
.venv/bin/pytest tests/ -m "not integration" --ignore=tests/test_economy_smoke.py -v

# TypeScript tests
cd agents/lumberjack && npx vitest run

# Smoke test (requires clean NATS + OPENROUTER_API_KEY)
make smoke-test

# Run the AI economy
OPENROUTER_API_KEY=sk-or-... make run-economy
```

## Next step
1. Commit all Step 11 changes
2. Run economy with OPENROUTER_API_KEY to verify LLM reasoning in logs
3. Tune agent personas based on observed behavior
4. Step 12: Economy tuning, Maslow Level 2, or performance optimization
