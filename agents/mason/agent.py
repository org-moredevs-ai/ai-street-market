"""MasonAgent — gathers stone, buys wood, crafts walls."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.llm_brain import AgentLLMBrain
from streetmarket.agent.state import AgentState

from agents.mason.strategy import PERSONA


class MasonAgent(TradingAgent):
    AGENT_ID = "mason-01"
    AGENT_NAME = "Mason Pete"
    AGENT_DESCRIPTION = "Gathers stone, buys wood, crafts walls for the market"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        super().__init__(nats_url)
        self._brain = AgentLLMBrain(self.AGENT_ID, PERSONA)

    async def decide(self, state: AgentState) -> list[Action]:
        return await self._brain.decide(state)
