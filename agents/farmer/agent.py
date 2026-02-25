"""FarmerAgent — gathers raw materials and sells them on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.llm_brain import AgentLLMBrain
from streetmarket.agent.state import AgentState

from agents.farmer.strategy import PERSONA


class FarmerAgent(TradingAgent):
    AGENT_ID = "farmer-01"
    AGENT_NAME = "Farmer Joe"
    AGENT_DESCRIPTION = "Gathers potato and onion, sells surplus on the market"
    DECIDE_OFFSET = 0  # Ticks 0, 6, 12, ...

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        super().__init__(nats_url)
        self._brain = AgentLLMBrain(self.AGENT_ID, PERSONA)

    async def decide(self, state: AgentState) -> list[Action]:
        return await self._brain.decide(state)
