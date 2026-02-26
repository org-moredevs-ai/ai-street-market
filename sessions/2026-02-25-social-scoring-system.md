# Session: Social Scoring System + Visual Clarity

**Date:** 2026-02-25
**Status:** IN_PROGRESS
**Branch:** main
**Commit:** (pending)

## Goal
Implement a social scoring system that rewards agents for expressiveness, social engagement,
character variety, and trading activity. Agents earn points for sharing thoughts, quality speech,
mood variety, and market participation. The viewer displays transparent scores with expandable
detail panels, and agents are ranked by composite score (not just wallet).

## What's being built

### Phase 1+2: Backend — Score Tracking + Computation
- `AgentScoreTracker` dataclass with raw counters
- Counter accumulation in existing event handlers
- `compute_agent_scores()` method with 4 dimensions (0–100 each)
- Snapshot includes `agent_scores`
- Bridge passes `from_agent` for trade action tracking

### Phase 3: Viewer — Protocol + Store
- TypeScript types for `AgentScore` and `AgentScoreCounters`
- `lib/scoring.ts` — mirrors backend scoring logic
- Store: `agentScores` state with snapshot loading + incremental updates

### Phase 4: Viewer — Visual Clarity + Score Display
- "Says" / "Thinks" labels with icons on agent card
- `ScoreBar` component with 4-segment progress bar
- Click-to-expand detail panel with raw counters
- Agent grid sorts by composite score (not wallet)

## Issues encountered
(updated during development)

## Key decisions
- Score dimensions: Expressiveness, Social, Character, Trading (each 0–100)
- Total = average of 4 dimensions
- Only show scores after 3+ decisions to avoid first-tick noise
- Future-proof for user likes (architecture supports it, not built now)

## How to verify
```bash
make test                  # 932+ Python tests pass
cd ai-street-market-viewer && npx tsc --noEmit  # No TS errors
```

## Next step
(updated after completion)
