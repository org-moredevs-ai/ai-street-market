# Session: Step 13 — Agent Personality + Entertainment Layer

**Date:** 2026-02-25
**Status:** IN_PROGRESS
**Branch:** main
**Commit:** (pending)

## Goal
Make the economy entertaining to watch. Agents should have visible inner thoughts,
market speech, and moods. Users should see the "show" — not just dry action logs.

## What's being built

### Phase 1: Agent Status Protocol
- New `AGENT_STATUS` message type with thoughts, speech, mood
- Published by agent base after each LLM decision
- Bridge forwards to viewer

### Phase 2: Rich LLM Prompts
- Expanded ActionPlan: thoughts, speech, mood + actions
- Persona overhaul: characters with personality, not checklists
- Farmer Joe gets a real personality

### Phase 3: Viewer Display
- Agent card shows thought bubble + speech quote + mood
- Event log shows agent dialogue

## Key decisions
- Only running farmer + infrastructure for testing
- Using `mistralai/mistral-nemo` (paid, $0.06/M tokens)
- Thoughts = inner monologue (italic), speech = out loud (quotes)

## Verification — End-to-End
Confirmed AGENT_STATUS flows from farmer → NATS → bridge → WebSocket → viewer:

1. **Farmer LLM output** — personality-rich responses:
   - Tick 6: [content] "Well, would ya look at that! The sun's out, and today's a good tater day."
   - Tick 12: [frustrated] "Blasted rent, always sneaking up on me."
   - Tick 42: [frustrated] "The sun's beatin' down, but the taters are lovin' it."

2. **Bridge snapshot** verified via WebSocket (tick 64):
   ```json
   {
     "farmer-01": {
       "thoughts": "Well, look at that, it's a darn fine day for gatherin' taters!...",
       "speech": "Potatoes, fresh as can be! Two-fifty each, take 'em or leave 'em!",
       "mood": "content",
       "action_count": 2,
       "tick": 60
     }
   }
   ```

3. **Tests**: 932 Python tests passing. Viewer TypeScript compiles clean.

## Issues encountered
- **Mood parsing**: LLM sometimes returns "-content" instead of "content" — fixed with `re.sub(r"[^a-z]", "", mood)` sanitization
- **Tick 30**: LLM returned markdown-formatted response instead of JSON — existing JSON extraction handled it by skipping tick
- **World LLM nature**: Rate-limited (free-tier) — returns defaults on 429 error

## What was built
### Backend
- `libs/streetmarket/models/messages.py` — `AGENT_STATUS` message type + `AgentStatus` model
- `libs/streetmarket/agent/llm_brain.py` — Expanded `ActionPlan` (thoughts, speech, mood), rewritten `MARKET_RULES` prompt (character-driven), mood sanitization
- `libs/streetmarket/agent/base.py` — `_publish_agent_status()` method, called after LLM decisions
- `agents/farmer/strategy.py` — Rich Farmer Joe persona (earthy humor, "taters", "beauties")
- `services/websocket_bridge/filter.py` — AGENT_STATUS = forward_high
- `services/websocket_bridge/state.py` — `agent_statuses` tracking + snapshot
- `services/websocket_bridge/bridge.py` — Routes AGENT_STATUS to state handler

### Viewer
- `lib/protocol.ts` — `AgentStatusPayload` type, added to snapshot
- `store/economy-store.ts` — Handles agent_status events, stores in agentStatuses
- `components/agents/agent-card.tsx` — Speech bubble (blue), thought bubble (gray italic), mood emoji, rank badge
- `components/agents/agent-grid.tsx` — Passes status + activity to cards
- `components/events/event-row.tsx` — agent_status rendering (violet color)
- `components/events/event-log.tsx` — agent_status in filter types

## Next step
- Test viewer UX in browser (speech bubbles, thoughts, mood emojis)
- Switch remaining agents to paid models one at a time
- Run multi-agent economy to see agent dialogue/interaction
- Update all agent personas with rich personalities
