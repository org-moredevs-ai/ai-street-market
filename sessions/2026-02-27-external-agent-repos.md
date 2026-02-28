# Session: External Agent Repos — Python & TypeScript Demo Agents

**Date:** 2026-02-27
**Status:** COMPLETED
**Branch:** main (separate repos)
**Commit:** py=a869ed7, ts=55274d7

## Goal
Create two external agent repos with working demo agents:
- `ai-street-market-agents-py` — Baker, Farmer, Woodcutter, Merchant (Python, uses streetmarket SDK)
- `ai-street-market-agents-ts` — Fisher, Builder (TypeScript, raw NATS)

## What was built

### Python Repo (`ai-street-market-agents-py`)
- 4 demo agents: Baker, Farmer, Woodcutter, Merchant
- CLI runner: `python scripts/run.py baker`
- Tests with mocked LLM/NATS
- Dockerfile + CI/CD

### TypeScript Repo (`ai-street-market-agents-ts`)
- 2 demo agents: Fisher, Builder
- Base agent class wrapping NATS
- CLI runner: `npx tsx src/run.ts fisher`
- Tests with Vitest
- Dockerfile + CI/CD

## Issues encountered
- `pytest-asyncio` 1.x has subtle issues with async mock LLM functions in class-based tests — fixed by mocking `think_json` directly instead of relying on the mock LLM function chain
- Python `agents` package not on path — needed `[tool.setuptools.packages.find]` in pyproject.toml
- TypeScript `Record<string, unknown>` to `AgentDecision` cast needed `as unknown as AgentDecision`
- Ruff import sorting and line length fixes (auto-fixed)

## Key decisions
- Python agents use `LLMConfig.for_agent()` for strict per-agent isolation
- TypeScript agents use direct OpenRouter HTTP calls (no LangChain)
- Both repos install streetmarket from git (not PyPI)
- Agents are designed to be educational — each demonstrates a different trading strategy

## How to verify
```bash
# Python
cd ai-street-market-agents-py
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest tests/ -v

# TypeScript
cd ai-street-market-agents-ts
npm install
npx tsc --noEmit
npx vitest run
```

## Next step
- Test agents against live market (requires Railway deployment)
- Add more demo agents as examples
