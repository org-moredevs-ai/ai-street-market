"""BakerAgent — buys potatoes, crafts bread, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from agents.baker.strategy import decide


class BakerAgent(TradingAgent):
    AGENT_ID = "baker-01"
    AGENT_NAME = "Baker Bella"
    AGENT_DESCRIPTION = "Buys potatoes, crafts bread, sells on the food market"

    def decide(self, state: AgentState) -> list[Action]:
        return decide(state)
