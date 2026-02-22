"""MasonAgent — gathers stone, buys wood, crafts walls, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from agents.mason.strategy import decide


class MasonAgent(TradingAgent):
    AGENT_ID = "mason-01"
    AGENT_NAME = "Mason Pete"
    AGENT_DESCRIPTION = "Gathers stone, buys wood, crafts walls, sells on the materials market"

    def decide(self, state: AgentState) -> list[Action]:
        return decide(state)
