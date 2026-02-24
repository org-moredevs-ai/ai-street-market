"""ChefAgent — buys ingredients, crafts soup, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.llm_brain import AgentLLMBrain
from streetmarket.agent.state import AgentState

from agents.chef.strategy import PERSONA


class ChefAgent(TradingAgent):
    AGENT_ID = "chef-01"
    AGENT_NAME = "Chef Clara"
    AGENT_DESCRIPTION = "Buys potato and onion, crafts soup, sells on the food market"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        super().__init__(nats_url)
        self._brain = AgentLLMBrain(self.AGENT_ID, PERSONA)

    async def decide(self, state: AgentState) -> list[Action]:
        return await self._brain.decide(state)
