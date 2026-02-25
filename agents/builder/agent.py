"""BuilderAgent — buys materials, crafts houses."""

from streetmarket.agent.actions import Action
from streetmarket.agent.base import TradingAgent
from streetmarket.agent.llm_brain import AgentLLMBrain
from streetmarket.agent.state import AgentState

from agents.builder.strategy import PERSONA


class BuilderAgent(TradingAgent):
    AGENT_ID = "builder-01"
    AGENT_NAME = "Builder Bob"
    AGENT_DESCRIPTION = "Buys walls, shelves, and furniture to craft houses"
    DECIDE_OFFSET = 4  # Ticks 4, 10, 16, ...

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        super().__init__(nats_url)
        self._brain = AgentLLMBrain(self.AGENT_ID, PERSONA)

    async def decide(self, state: AgentState) -> list[Action]:
        return await self._brain.decide(state)
