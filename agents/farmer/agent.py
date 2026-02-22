"""FarmerAgent — gathers raw materials and sells them on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from agents.farmer.strategy import decide


class FarmerAgent(TradingAgent):
    AGENT_ID = "farmer-01"
    AGENT_NAME = "Farmer Joe"
    AGENT_DESCRIPTION = "Gathers potato and onion, sells surplus on the market"

    def decide(self, state: AgentState) -> list[Action]:
        return decide(state)
