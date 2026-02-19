# Session: Step 2 — Governor Agent

**Date:** 2026-02-19
**Status:** COMPLETED
**Branch:** main
**Commit:** (see git log)

## Goal
Implement the Governor Agent — the first service in the AI Street Market. The Governor subscribes to `market.>`, validates every trade message against Phase 1 rules (no LLM, pure hardcoded rules), and publishes `ValidationResult` messages to `/market/governance`.

Phase 1 rules cover: message structure, catalogue compliance, rate limiting, recipe correctness, and agent activity. No wallet/inventory validation (that's Step 3 — Banker).

## What was built

### Phase 1: Catalogue Data
- `libs/streetmarket/models/catalogue.py` — `CatalogueItem`, `Recipe` models, `ITEMS` dict (5 raw + 5 crafted), `RECIPES` dict (soup, shelf, wall, furniture, house), `is_valid_item()`, `is_valid_recipe()` helpers
- Updated `libs/streetmarket/models/__init__.py` and `libs/streetmarket/__init__.py` with new exports
- `tests/test_catalogue.py` — 18 tests covering items, recipes, data integrity

### Phase 2: Governor State
- `services/__init__.py` + `services/governor/__init__.py` — package markers
- `services/governor/state.py` — `GovernorState` dataclass with tick advancement, rate limiting (MAX_ACTIONS_PER_TICK=5), heartbeat tracking (HEARTBEAT_TIMEOUT_TICKS=10), agent registration, crafting state
- `tests/test_governor_state.py` — 20 tests

### Phase 3: Business Rules
- `services/governor/rules.py` — `validate_envelope_structure()` (delegates to shared lib), `validate_business_rules()` with per-type validation: offer/bid (catalogue check), accept/counter (reference_msg_id), craft_start (recipe+inputs+ticks+not-already-crafting), craft_complete (has active craft), join (register), heartbeat (record)
- `tests/test_governor_rules.py` — 26 tests

### Phase 4: Governor Agent
- `services/governor/governor.py` — `GovernorAgent` class subscribing to `market.>` and `/system/tick`, dispatching structural + business validation, publishing `ValidationResult` to `/market/governance`
- `services/governor/__main__.py` — async entry point with signal handling
- Added `governor` target to `Makefile`

### Phase 5: Integration Tests
- `tests/test_governor_integration.py` — 5 tests: valid offer accepted, unknown item rejected, invalid recipe rejected, rate limiting, self-message loop prevention

## Test Results
- 115 tests total (106 unit + 9 integration), all passing
- New tests: 18 catalogue + 20 state + 26 rules + 5 integration = 69 new tests

## Issues encountered
- Pre-existing ruff import sorting issues in Step 1 files — auto-fixed with `ruff check --fix`
- Unused imports in test_catalogue.py (CatalogueItem, Recipe) — auto-fixed by ruff

## Key decisions
- Catalogue in shared library so all agents can import the same data
- Subscribe to `market.>` wildcard, filter own `validation_result` messages by `from_agent == "governor"` + `type == VALIDATION_RESULT`
- In-memory state only, resets per-tick counters on `advance_tick()`
- Rate limit counts all messages (even invalid ones) — prevents spam flooding
- `craft_start`/`craft_complete` update state during validation (acceptable in single-threaded async)
- Replaced `services/.gitkeep` with proper `services/__init__.py`

## How to verify
```bash
# Unit tests (no NATS)
.venv/bin/pytest tests/test_catalogue.py tests/test_governor_state.py tests/test_governor_rules.py -v

# All tests including integration
make infra-up && make test

# Run governor manually
make governor
# In another terminal
make proof-of-life

make infra-down
```

## Next step
Step 3 — Banker Agent
