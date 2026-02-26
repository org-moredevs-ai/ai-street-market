# Session: Step 12B — Economy Fixes + Viewer UX Overhaul

**Date:** 2026-02-25
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Fix 1 critical backend bug (Banker rate-limited by Governor) and 11 UX issues found during 14-hour economy run. Changes span backend and viewer repos.

## What was built

### Phase 1: Critical Backend Fix (B1)
- **`services/governor/state.py`**: Added `SERVICE_IDS` frozenset exempting banker, world, governor, town_crier, websocket_bridge from rate limiting
- **`services/governor/state.py`**: Added `market_open` flag, set True on first `advance_tick()`
- **Tests**: 6 new tests in `test_governor_state.py` (service exemption, market open)

### Phase 2: Backend Data Enrichment (U1, U2, U3, U9, U11)
- **`services/websocket_bridge/state.py`**: Complete rewrite with:
  - `narration_history`: deque[dict] (max 20) — fixes U1, U2
  - `energy_deltas`: dict computed on each ENERGY_UPDATE — fixes U9
  - `town_treasury` + `total_rent_collected`: from RENT_DUE events — fixes U11
  - `agent_inventories`: from heartbeat `inventory_count` field
  - `on_settlement()`: reads `buyer_wallet_after`, `seller_wallet_after`
  - `on_nature_event()`: computes `end_tick`; `on_tick()` prunes expired events — fixes U3
  - `get_snapshot()`: includes all new fields (narrations, energy_deltas, treasury, inventories)
- **`libs/streetmarket/models/messages.py`**: Settlement + RentDue models extended with new optional fields
- **`services/banker/state.py`**: Added `town_treasury` + `total_rent_collected` fields
- **`services/banker/rules.py`**: Rent processing accumulates treasury
- **`services/banker/banker.py`**: Publishes `buyer_wallet_after`/`seller_wallet_after` in settlements, treasury in rent
- **Tests**: 20+ new tests in `test_bridge_state.py`

### Phase 3: Viewer Frontend Fixes (U4, U5, U8, U9, U10)
- **`lib/protocol.ts`**: EconomySnapshot extended: narrations, energy_deltas, town_treasury, total_rent_collected, agent_inventories
- **`store/economy-store.ts`**: Complete rewrite:
  - `applySnapshot`: reads narrations array (not just latest_narration) — fixes U1, U2
  - `join` event: initializes wallet to 100.0 — fixes U4
  - `settlement` event: updates wallets from buyer_wallet_after/seller_wallet_after
  - `energy_update` event: computes deltas — fixes U9
  - `rent_due` event: tracks treasury_balance + total_rent_collected — fixes U11
  - New state fields: energyDeltas, agentInventories, townTreasury, totalRentCollected
- **`components/agents/agent-grid.tsx`**: Sorted by wallet descending, bankrupt last; shows agent count + treasury — fixes U8
- **`components/agents/agent-card.tsx`**: Complete rewrite:
  - Rank badges (#1 gold, #2 silver, #3 bronze) — fixes U8
  - "Idle" (amber) instead of "Inactive" (gray), only opacity-60 after 50+ ticks — fixes U5
  - "last seen: tick N" displayed for idle agents — fixes U5
  - Energy delta (+5 green / -10 red) below energy label — fixes U9
  - Inventory count shown next to joined tick
- **`app/market/page.tsx`**: "Market Ticker" → "Trading Floor", "Recent Settlements" → "Recent Trades" — fixes U10
- **`components/market/settlement-feed.tsx`**: Buyer green, seller orange; shows wallet-after — fixes U10
- **`components/market/rent-summary.tsx`**: **NEW** — Treasury balance + total rent collected — fixes U11

### Phase 4: Protocol Improvements (U6, U7)
- **`services/governor/rules.py`**: `_handle_join()` now validates:
  - Market open check (rejects before first tick) — fixes U7
  - Empty agent_id check
  - Duplicate join allowed silently (agent restart)
- **`services/governor/governor.py`**: Publishes JOIN validation result to agent inbox — fixes U6
- **`libs/streetmarket/agent/base.py`**: JOIN admission flow:
  - Sends JOIN, waits up to 1s for validation result from inbox
  - On acceptance: sets joined=True, wallet=100
  - On rejection: logs warning, retries next tick
  - Skips LLM decisions while join pending
- **Tests**: 3 new tests in `test_governor_rules.py` (market open, duplicate join)
- Fixed `test_governor_energy.py`: updated state construction to use advance_tick()

## Issues encountered
- `GovernorState(current_tick=5)` in test didn't trigger `market_open=True` — tests need `advance_tick()` instead of constructor arg
- The `_handle_join` return type changed from None to list[str] — had to update call site in `validate_business_rules`

## Key decisions
- **Treasury is read-only in bridge** — values come from Banker via RENT_DUE messages, bridge just tracks latest
- **Nature event expiry** computed as `end_tick = current_tick + duration_ticks` on arrival, pruned each tick
- **Energy deltas** computed in both bridge (Python) and store (TypeScript) for consistency
- **JOIN admission** uses 1-second timeout with polling, falls back to retry on next tick
- **Duplicate joins allowed silently** — agents may restart and re-join

## How to verify
```bash
# Backend tests
make test                                    # 932 Python tests pass
cd agents/lumberjack && npm test             # 52 TypeScript tests pass
# Viewer type check
cd ../ai-street-market-viewer && npx tsc --noEmit  # Clean compile

# Run economy
make infra-up
make run-economy

# Verify in viewer (http://localhost:3000):
# B1: No Banker rate-limit rejections in logs
# U1: Tick shows real tick number (correct snapshot)
# U2: Narrations visible on Square page from start
# U3: Nature events expire and get pruned
# U4: Agents enter with wallet 100 (not 0)
# U5: Idle badge is amber with "last seen tick N"
# U6: JOIN validated with admission response
# U7: Agents wait for market open before joining
# U8: Agents ranked by wallet (descending)
# U9: Energy shows +/- deltas on agent cards
# U10: Market page shows "Trading Floor" + "Recent Trades"
# U11: Rent summary shows treasury balance
```

## Next step
Step 13: Viewer UX polish, paid model demo, action queuing, agent memory
