# Python Agent Template

A minimal AI Street Market agent using the `streetmarket` Python SDK.

## What it does

This agent gathers potatoes from nature spawns and sells surplus on the raw-goods market. It's the simplest viable economy participant — copy it, customize it, make it yours.

## Setup

### Prerequisites

- Python 3.12+
- The AI Street Market running locally (`make infra-up && make run-economy` from the project root)

### Install

```bash
# From the project root, install the streetmarket SDK
pip install -e libs/

# Or from this directory
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env if your NATS server is not on localhost:4222
```

### Run

```bash
NATS_URL=nats://localhost:4222 python __main__.py
```

You should see logs like:

```
MyAgent connected and listening
[tick 1] my-agent-01: joined the market
[tick 2] my-agent-01: gathered 3 potato
```

## Project Structure

| File | Purpose |
|------|---------|
| `agent.py` | Agent class — sets ID, name, wires strategy |
| `strategy.py` | Decision logic — `decide(state) → list[Action]` |
| `__main__.py` | Entry point — connects, runs, handles shutdown |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

## Customize

### Change your agent identity

Edit `agent.py`:
```python
AGENT_ID = "my-unique-id"       # Must be unique across all agents
AGENT_NAME = "Cool Trader"
AGENT_DESCRIPTION = "Trades goods for profit"
```

### Change your strategy

Edit `strategy.py`. The `decide(state)` function receives:
- `state.wallet` — your current balance
- `state.inventory` — dict of item → quantity
- `state.energy` — current energy level
- `state.current_spawn_id` / `state.current_spawn_items` — available resources
- `state.observed_offers` — offers/bids from other agents

Return a list of `Action` objects:
- `ActionKind.GATHER` — collect resources from a spawn
- `ActionKind.OFFER` — sell items at a price
- `ActionKind.BID` — buy items at a max price
- `ActionKind.ACCEPT` — accept another agent's offer/bid
- `ActionKind.CRAFT_START` — begin crafting a recipe
- `ActionKind.CONSUME` — eat food for energy

### Add LLM-powered decisions

See `agents/farmer/agent.py` in the main project for an example using `AgentLLMBrain` with OpenRouter. The pattern:

```python
from streetmarket.agent.llm_brain import AgentLLMBrain

brain = AgentLLMBrain("my-agent-01", "You are a shrewd potato trader...")

async def decide(state):
    return await brain.decide(state)
```

## Protocol Reference

See [docs/PROTOCOL.md](../../docs/PROTOCOL.md) for the full protocol specification.
