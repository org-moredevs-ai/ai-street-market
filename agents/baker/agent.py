"""BakerAgent — buys potato, crafts bread, sells on the market."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.llm_brain import AgentLLMBrain
from streetmarket.agent.state import AgentState

from agents.baker.strategy import PERSONA


class BakerAgent(TradingAgent):
    AGENT_ID = "baker-01"
    AGENT_NAME = "Baker Bella"
    AGENT_DESCRIPTION = "Buys potato, crafts bread, sells on the food market"
    DECIDE_OFFSET = 2  # Ticks 2, 8, 14, ...

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        super().__init__(nats_url)
        self._brain = AgentLLMBrain(self.AGENT_ID, PERSONA)

    async def decide(self, state: AgentState) -> list[Action]:
        return await self._brain.decide(state)
