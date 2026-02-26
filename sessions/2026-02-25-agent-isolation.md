# Session: Agent Isolation — Strict Per-Agent API Keys

**Date:** 2026-02-25
**Status:** COMPLETED
**Branch:** main
**Commit:** (fill when done)

## Goal
Enforce **strict** agent isolation: every agent MUST have its own API key and model. No shared fallbacks for agents. The economy runner refuses to start unless every agent has `{PREFIX}_API_KEY` and `{PREFIX}_MODEL` set.

Services (Governor, Banker, World, Town Crier) are market infrastructure and MAY use shared defaults.

## What was built

### Phase 1: Fallback approach (rejected by user)
Initially implemented per-agent keys WITH fallback to `OPENROUTER_API_KEY`. User rejected: "fix it. do not allow violations."

### Phase 2: Strict enforcement (final)

1. **`libs/streetmarket/agent/llm_config.py`** — Complete rewrite:
   - `for_agent()` raises `KeyError` if `{PREFIX}_API_KEY` missing, `ValueError` if `{PREFIX}_MODEL` missing
   - NO fallback to `OPENROUTER_API_KEY` or `DEFAULT_MODEL` for agents
   - Added `AGENT_PREFIXES` constant: `("FARMER", "CHEF", "BAKER", "MASON", "BUILDER", "LUMBERJACK")`
   - `for_service()` unchanged — services MAY use shared defaults

2. **`agents/lumberjack/src/llm_brain.ts`** — Strict TypeScript config:
   - `loadConfig()` throws if `LUMBERJACK_API_KEY` or `LUMBERJACK_MODEL` missing
   - No fallback to `OPENROUTER_API_KEY` for agent key (API base fallback is fine)

3. **`scripts/run_economy.py`** — Pre-launch validation:
   - `_validate_agent_env()` checks ALL agent prefixes from `AGENT_PREFIXES`
   - Economy refuses to start with clear error listing missing vars
   - Services validated separately (shared OR per-service keys)

4. **`tests/test_agent_llm_brain.py`** — Split test classes:
   - `TestLLMConfigAgent` (12 tests) — strict isolation enforcement
   - `TestLLMConfigService` (3 tests) — shared defaults allowed
   - Old `env_vars` fixture → `agent_env` (per-agent) + `service_env` (shared)
   - `TestAgentLLMBrain` updated to use `agent_env` fixture

5. **`tests/test_ai_guardrails.py`** — New guardrails:
   - `TestStrictAgentIsolation` (4 tests) — code-level enforcement
   - Verifies `for_agent()` body has no `OPENROUTER_API_KEY`/`DEFAULT_MODEL` fallback
   - Verifies lumberjack TS throws on missing key
   - Verifies `AGENT_PREFIXES` lists all agents
   - Updated `TestEconomyRunnerChecksAPIKey` to also check `_validate_agent_env`

6. **`.env.example`** — Per-agent keys now REQUIRED (not commented out):
   - All 6 agents have `{PREFIX}_API_KEY` and `{PREFIX}_MODEL` as mandatory lines
   - Service keys remain optional (commented)

## Issues encountered
- `env_vars` fixture rename broke `TestAgentLLMBrain` — had to update all 8 method signatures
- Lumberjack TS uses template literals (`${prefix}_API_KEY`), so guardrail test needed pattern match instead of literal string match

## Key decisions
- **No shared fallback for agents** — `for_agent()` raises, never falls back
- **Services keep shared fallback** — they're infrastructure, not external participants
- **Pre-launch validation** — economy runner checks ALL agents before starting ANY
- **Guardrail tests** — structural code analysis ensures no future regression

## How to verify
```bash
make test  # 907 Python tests pass
```

## Next step
Continue with Step 12 (Protocol Spec + Agent Templates) or Step 13 (Viewer UX, paid model demo)
