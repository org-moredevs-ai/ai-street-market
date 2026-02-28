# Session: Market-Side Message Sanitization

**Date:** 2026-02-28
**Status:** COMPLETED
**Branch:** main
**Commit:** (fill when done)

## Goal
Add `sanitize_message()` to the shared library and call it in `MarketBusClient.publish()` — the single point where ALL messages enter JetStream. This cleans up LLM artifacts (JSON wrapping, code fences, control chars) from both trading agents (untrusted) and market agents (defense-in-depth).

## What was built
1. **`libs/streetmarket/helpers/sanitize.py`** — `sanitize_message()` function
   - Strips control characters (keeps tab, newline, CR)
   - Strips markdown code fences
   - Unwraps JSON-wrapped messages (extracts `"message"` value)
   - Collapses 3+ newlines to 2
   - Truncates to 2000 chars
   - Trims whitespace

2. **`libs/streetmarket/client/nats_client.py`** — integrated sanitize call in `publish()`

3. **`tests/test_sanitize.py`** — comprehensive tests

## Issues encountered
None — clean implementation, all tests passed on first run (446 total: 420 existing + 26 new).

## Key decisions
- Sanitize at `publish()` level (single chokepoint) rather than per-agent
- Always pass through, never block — worst case is cleaned text
- 2000 char limit is generous for natural language, prevents DoS

## How to verify
```bash
make test
```

## Next step
Deploy to staging and verify viewer shows clean messages.
