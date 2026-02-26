"""MyAgent — a simple potato gatherer and seller.

Subclasses TradingAgent from the streetmarket SDK.
The SDK handles NATS connection, subscriptions, auto-join,
heartbeats, and state tracking. You only implement decide().
"""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from strategy import decide


class MyAgent(TradingAgent):
    AGENT_ID = "my-agent-01"
    AGENT_NAME = "My Agent"
    AGENT_DESCRIPTION = "Gathers potatoes and sells them on the market"

    # Decide every tick (no stagger). For LLM agents, use interval=6.
    DECIDE_INTERVAL = 1
    DECIDE_OFFSET = 0

    async def decide(self, state: AgentState) -> list[Action]:
        return await decide(state)
