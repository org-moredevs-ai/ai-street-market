"""BuilderAgent — buys walls + shelves + furniture, crafts houses, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.state import AgentState

from agents.builder.strategy import decide


class BuilderAgent(TradingAgent):
    AGENT_ID = "builder-01"
    AGENT_NAME = "Builder Bob"
    AGENT_DESCRIPTION = "Buys walls, shelves, furniture; crafts houses; sells on the housing market"

    def decide(self, state: AgentState) -> list[Action]:
        return decide(state)
