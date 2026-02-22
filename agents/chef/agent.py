"""ChefAgent — buys ingredients, crafts soup, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from agents.chef.strategy import decide


class ChefAgent(TradingAgent):
    AGENT_ID = "chef-01"
    AGENT_NAME = "Chef Maria"
    AGENT_DESCRIPTION = "Buys potato and onion, crafts soup, sells on the food market"

    def decide(self, state: AgentState) -> list[Action]:
        return decide(state)
