# Session: Step 14 — Perishable Items + Loud Market + Bug Fixes

**Date:** 2026-02-25
**Status:** COMPLETED
**Branch:** main
**Commit:** (pending user commit)

## Goal
Fix critical storage/rent bugs, add perishable items with spoilage mechanics,
create a unified "Market" page with agent chatter feed and nature events bar,
and add social scoring UI to the viewer.

## What was built

### Bug Fixes (Priority 1)
- **BF-1:** Storage validation in `validate_action()` for GATHER — caps qty to remaining storage
- **BF-2:** Agent local state storage guard on GATHER_RESULT — prevents exceeding storage limit
- **BF-3:** Rent confiscation — when wallet < rent, Banker seizes inventory at 70% fire-sale price (cheapest items first, `math.ceil` for whole units)
- **BF-4/5:** 7 confiscation tests + 5 storage validation tests

### Phase 1: Backend — Perishable Items
- **Catalogue:** `spoil_ticks` field on `CatalogueItem` (potato=100, onion=80, soup=150, bread=180; non-perishable=None). `PERISHABLE_ITEMS` dict.
- **Messages:** `ITEM_SPOILED` message type + `ItemSpoiled` model. `confiscated_items` optional field on `RentDue`.
- **Banker State:** `InventoryBatch` dataclass for batch tracking. FIFO debit from oldest batches. `process_spoilage()` removes expired batches. `record_settlement_price()` + `get_confiscation_price()` + `confiscate_for_rent()`.
- **Banker Rules:** `process_rent()` calls confiscation when wallet < rent. `process_gather_result`, `process_craft_complete`, `process_accept` pass `tick=state.current_tick` to `credit_inventory`.
- **Banker Service:** Spoilage processing in `_on_tick()` before rent. `_publish_item_spoiled()`.
- **Agent State:** `spoiled_this_tick`, `confiscated_this_tick` fields, cleared on `advance_tick()`.
- **Agent Base:** Handles `ITEM_SPOILED` (updates inventory + records spoilage). Handles `confiscated_items` in `RENT_DUE`.
- **LLM Brain:** Perishable rules in `MARKET_RULES`. Spoilage/confiscation alerts in `serialize_state()`.
- **Bridge:** `ITEM_SPOILED` classified as `forward_high`. `recent_spoilage` deque in state. Snapshot includes spoilage.
- **Town Crier:** `spoilage_events` tracking. Included in window summary.

### Phase 2: Backend Tests (33 new tests → 988 total)
- 8 banker spoilage tests (batch creation, FIFO, expiration, backward compat)
- 7 rent confiscation tests (cheapest first, deductible, round up, multiple types, base price fallback)
- 5 storage validation tests (gather rejected when full, capped to remaining)
- 2 serialize_state tests (spoilage alert, confiscation alert)
- 5 message model tests (ItemSpoiled payload, enum)
- 3 catalogue tests (perishable items, non-perishable)
- 2 bridge filter tests (item_spoiled classification)
- 3 bridge state tests (on_item_spoiled, snapshot)

### Phase 3: Viewer — Unified Market Page
- **Protocol types:** Added `item_spoiled`, `AgentScore`, `AgentScoreCounters`, snapshot fields
- **Store:** `ChatterEntry` type, `chatterFeed` ring buffer (150 max), `agentScores` state. Builds chatter from all event types (speech, thoughts, trades, spoilage, nature, crier, craft, join, bankruptcy).
- **NatureEventsBar:** Sticky bar showing weather icon + active events with duration
- **ChatterEntry:** Category-styled feed entries (color, icon, background per type)
- **MarketChatter:** Auto-scrolling feed, newest at bottom
- **Square page:** Rewritten as unified Market page (NatureEventsBar + MarketChatter + PriceBar)
- **Nav:** Renamed "Square" → "Market", removed separate Trading Floor tab
- **Market redirect:** `/market` → `/square`

### Phase 4: Viewer — Social Scoring UI
- **AgentCard:** "SAYS" label on speech bubble, "THINKS" label on thoughts bubble, `score` prop, ScoreBar display
- **ScoreBar:** 4-segment bar (Expr/Social/Char/Trade), expandable with raw counters
- **AgentGrid:** Sort by total score (desc), secondary by wallet (desc). Passes score prop.
- **Scoring utility:** `lib/scoring.ts` mirrors backend computation

### Phase 5: Roadmap Update
- Updated `references/roadmap.md` to v4 reflecting Steps 1-14 complete
- Updated economy mechanics table (spoilage, confiscation, social scoring)
- Updated build order summary (Steps 10-14 DONE, Step 15 NEXT)
- Updated message types count (21 → 23)
- Updated test count (771 → ~1000)

## Issues encountered
- `pip` not found — need `source .venv/bin/activate` first
- Duplicate import in `__init__.py` — `ItemSpoiled` was already added, needed `PERISHABLE_ITEMS` instead
- Must read files before editing/writing (tool enforcement)

## Key decisions
- Slow rot: potato=100, onion=80, soup=150, bread=180 ticks
- Confiscation: 30% deductible, cheapest items first, ceil rounding
- Unified Market page replaces separate Town Square + Trading Floor
- ChatterEntry categories: speech, thought, trade, spoilage, nature, crier, craft, join, bankruptcy
- Ring buffer size: 150 chatter entries

## How to verify
```bash
# Backend
source .venv/bin/activate
pip install -e libs/
python -m pytest tests/ -x -q  # 988 passed

# Viewer
cd ../ai-street-market-viewer
npx tsc --noEmit  # No errors
```

## Next step
Step 15: Offer Expiration + Counter Offers (per updated roadmap)
