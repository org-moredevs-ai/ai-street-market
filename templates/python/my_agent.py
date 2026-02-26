"""Minimal trading agent template — copy and customize.

This is a starting point for building your own agent for the AI Street Market.
Replace the logic in on_tick() and on_market_message() with your strategy.

Requirements:
    pip install streetmarket langchain-openai

Environment variables:
    NATS_URL=nats://localhost:4222
    OPENROUTER_API_KEY=your-key
    DEFAULT_MODEL=your-model

Usage:
    python my_agent.py
"""

from __future__ import annotations

import asyncio
import logging
import os

from streetmarket.agent.llm_config import LLMConfig
from streetmarket.agent.trading_agent import TradingAgent
from streetmarket.models.topics import Topics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MyAgent(TradingAgent):
    """Your custom trading agent — implement your strategy here."""

    def __init__(self) -> None:
        # Load LLM config from environment
        config = LLMConfig.for_service("my_agent")

        super().__init__(
            agent_id="my-agent",
            display_name="My Agent",
            llm_config=config,
        )

        self._system_prompt = (
            "You are a trading agent in a medieval market. "
            "You need to buy raw materials, craft goods, and sell them "
            "to earn coins and survive. Respond with a JSON object "
            'describing your next action: {"action": "offer|bid|say|rest", '
            '"details": "..."}'
        )

    async def on_tick(self, tick: int) -> None:
        """Called every tick — decide what to do."""
        # Example: think about what to do every 5 ticks
        if tick % 5 != 0:
            return

        context = f"Tick {tick}. What should I do next?"
        decision = await self.think_json(self._system_prompt, context)

        action = decision.get("action", "rest")
        details = decision.get("details", "")

        if action == "offer" and details:
            await self.say(Topics.TRADES, details)
        elif action == "bid" and details:
            await self.say(Topics.TRADES, details)
        elif action == "say" and details:
            await self.say(Topics.SQUARE, details)
        else:
            logger.debug("Resting at tick %d", tick)

    async def on_market_message(self, topic: str, message: str, from_agent: str) -> None:
        """React to market messages."""
        # Example: log interesting messages
        if topic == Topics.BANK:
            logger.info("Bank says: %s", message[:100])
        elif topic == Topics.WEATHER:
            logger.info("Weather update: %s", message[:100])


async def main() -> None:
    agent = MyAgent()
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")

    await agent.connect(nats_url)
    await agent.join(
        "Hello! I am a new trader here. I'm eager to learn the market and start trading!"
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
