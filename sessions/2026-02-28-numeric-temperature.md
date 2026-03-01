# Session: Add Numeric Temperature (Celsius + Fahrenheit)

**Date:** 2026-02-28
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Add numeric temperature support to the weather system. The Meteo LLM now decides a `temperature_celsius` integer alongside the existing label. Fahrenheit is computed deterministically (`C × 9/5 + 32`). Both values flow through the pipeline: Weather → snapshot → bridge → viewer.

## What was built

### Weather dataclass (`libs/streetmarket/world_state/store.py`)
- Added `temperature_celsius: int | None = None` field to `Weather` dataclass

### Meteo agent (`services/meteo/meteo.py`)
- Added `temperature_celsius` to the JSON schema in `build_system_prompt()`
- Added instruction that it's an integer in degrees Celsius matching the label
- Updated `on_tick()` to extract and pass `temperature_celsius` through in the `WEATHER_CHANGE` event (with int coercion + error handling)

### WebSocket bridge (`services/websocket_bridge/bridge.py`)
- Updated `_build_state_snapshot()` to include `temperature_celsius` and computed `temperature_fahrenheit` in the weather dict
- Only includes these fields when `temperature_celsius` is not None (backward compatible)

### Snapshot persistence (`libs/streetmarket/persistence/snapshots.py`)
- Save: automatic via `asdict()` (dataclass field)
- Restore: updated `_apply_world_state()` to read `temperature_celsius` from snapshot data

### Tests (514 passing)
- `test_world_state.py`: Added `temperature_celsius is None` default assertion
- `test_websocket_bridge.py`: Updated snapshot test with celsius=22/fahrenheit=72, added test for None case
- `test_snapshots.py`: Added celsius=12 to test weather, verified round-trip
- `test_market_agent.py`: Added celsius to Meteo LLM responses, verified in event data

### Documentation
- `docs/VIEWER-PROTOCOL.md`: Added `temperature_celsius` and `temperature_fahrenheit` to weather schema example
- `docs/WORLD-STATE.md`: Added `temperature_celsius` to weather schema

## Issues encountered
None — clean implementation.

## Key decisions
- `temperature_celsius` is `int | None` — None for backward compatibility with existing weather data
- Fahrenheit computed only in bridge (viewer-facing), not stored in world state (deterministic math, not LLM)
- Bridge omits both C and F keys when celsius is None (no null pollution in viewer data)
- Meteo coerces LLM output to int with try/except for robustness

## How to verify
```bash
make test   # 514 tests pass
```

## Next step
No immediate follow-up needed. Feature is complete and ready for commit.
