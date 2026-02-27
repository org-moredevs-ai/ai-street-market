"""TradingAgent — SDK for external agents participating in the market.

This is the client-side framework that external agents use to:
- Connect to the market via NATS
- Send natural language messages
- Receive and parse market responses
- Use LLM for decision-making

External agents are untrusted participants. They can ONLY communicate
via natural language on public topics. They never see structured events
or internal market data.

Usage:
    class MyBaker(TradingAgent):
        async def on_tick(self, tick: int) -> None:
            # Decide what to do each tick
            ...

        async def on_market_message(self, topic: str, message: str, from_agent: str) -> None:
            # React to market messages
            ...

    agent = MyBaker(agent_id="baker-hugo", display_name="Hugo's Bakery")
    await agent.connect("nats://localhost:4222")
    await agent.join("I am Hugo's Bakery, specializing in fresh bread!")
    await agent.run()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from streetmarket.agent.llm_brain import extract_json
from streetmarket.agent.llm_config import LLMConfig
from streetmarket.client.nats_client import MarketBusClient
from streetmarket.helpers.factory import create_message
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics

logger = logging.getLogger(__name__)

# Type for the LLM callable
LLMFunction = Callable[[str, str], Coroutine[Any, Any, str]]


class TradingAgent:
    """Base class for external trading agents.

    Subclasses implement:
    - on_tick: called every tick to make decisions
    - on_market_message: called for market messages

    The agent handles NATS connection, message routing, and provides
    helpers for common actions (say, offer, bid, etc.).
    """

    def __init__(
        self,
        *,
        agent_id: str,
        display_name: str = "",
        llm_fn: LLMFunction | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.display_name = display_name or agent_id.replace("-", " ").title()
        self._client: MarketBusClient | None = None
        self._tick = 0
        self._running = False
        self._joined = False

        # LLM function: injected for tests, or created from config
        if llm_fn is not None:
            self._llm = llm_fn
        elif llm_config is not None:
            from streetmarket.agent.market_agent import create_llm_fn

            self._llm = create_llm_fn(llm_config)
        else:
            self._llm = None  # type: ignore[assignment]

    @property
    def current_tick(self) -> int:
        return self._tick

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def is_joined(self) -> bool:
        return self._joined

    # -- Connection --

    async def connect(self, nats_url: str = "nats://localhost:4222") -> None:
        """Connect to the market NATS bus."""
        self._client = MarketBusClient(nats_url)
        await self._client.connect()

        # Subscribe to public topics
        await self._client.subscribe(Topics.TICK, self._on_envelope)
        await self._client.subscribe(Topics.SQUARE, self._on_envelope)
        await self._client.subscribe(Topics.TRADES, self._on_envelope)
        await self._client.subscribe(Topics.BANK, self._on_envelope)
        await self._client.subscribe(Topics.WEATHER, self._on_envelope)
        await self._client.subscribe(Topics.PROPERTY, self._on_envelope)
        await self._client.subscribe(Topics.NEWS, self._on_envelope)
        await self._client.subscribe(Topics.agent_inbox(self.agent_id), self._on_envelope)

        logger.info("%s connected to %s", self.agent_id, nats_url)

    async def disconnect(self) -> None:
        """Disconnect from the market."""
        self._running = False
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("%s disconnected", self.agent_id)

    # -- Joining --

    async def join(self, introduction: str) -> None:
        """Introduce yourself to the market (triggers Governor onboarding).

        Args:
            introduction: Natural language introduction of who you are
                and what you plan to do in the market.
        """
        await self.say(Topics.SQUARE, introduction)
        self._joined = True
        logger.info("%s sent join message", self.agent_id)

    # -- Communication --

    async def say(self, topic: str, message: str) -> None:
        """Say something on a public topic.

        Args:
            topic: The topic to publish on (e.g., Topics.SQUARE).
            message: Natural language message.
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        envelope = create_message(
            from_agent=self.agent_id,
            topic=topic,
            message=message,
            tick=self._tick,
        )
        await self._client.publish(topic, envelope)
        logger.debug("%s -> %s: %s", self.agent_id, topic, message[:100])

    async def offer(self, item: str, quantity: int, price: float) -> None:
        """Announce an offer to sell items.

        Args:
            item: What you're selling.
            quantity: How many.
            price: Price per unit.
        """
        message = (
            f"I have {quantity} {item} for sale at {price} coins each. "
            f"Total: {quantity * price} coins. Any takers?"
        )
        await self.say(Topics.TRADES, message)

    async def bid(self, item: str, quantity: int, price: float) -> None:
        """Announce a bid to buy items.

        Args:
            item: What you want to buy.
            quantity: How many.
            price: Price per unit you're willing to pay.
        """
        message = (
            f"Looking to buy {quantity} {item} at {price} coins each. "
            f"Budget: {quantity * price} coins."
        )
        await self.say(Topics.TRADES, message)

    async def ask_banker(self, question: str) -> None:
        """Ask the Banker a question (balance, transaction status, etc.)."""
        await self.say(Topics.BANK, question)

    async def ask_landlord(self, question: str) -> None:
        """Ask the Landlord about properties."""
        await self.say(Topics.PROPERTY, question)

    # -- LLM Reasoning --

    async def think(self, system_prompt: str, context: str) -> str:
        """Use the LLM to reason about a situation.

        Args:
            system_prompt: System prompt defining the agent's personality.
            context: The current situation to reason about.

        Returns:
            Raw LLM text response, or empty string if no LLM configured.
        """
        if self._llm is None:
            return ""
        try:
            return await self._llm(system_prompt, context)
        except Exception:
            logger.exception("%s: LLM reasoning failed", self.agent_id)
            return ""

    async def think_json(self, system_prompt: str, context: str) -> dict[str, Any]:
        """Use the LLM to reason and return structured JSON."""
        raw = await self.think(system_prompt, context)
        if not raw:
            return {}
        try:
            return extract_json(raw)
        except ValueError:
            logger.warning(
                "%s: Could not extract JSON from response: %s",
                self.agent_id,
                raw[:200],
            )
            return {}

    # -- Event Handling --

    async def on_tick(self, tick: int) -> None:
        """Called on each tick. Override to implement agent logic.

        This is where you decide what to do: gather resources, craft items,
        make trades, eat food, rest, etc.
        """

    async def on_market_message(self, topic: str, message: str, from_agent: str) -> None:
        """Called for each market message. Override to react.

        Args:
            topic: The topic the message was on.
            message: The natural language message content.
            from_agent: Who sent the message.
        """

    # -- Internal --

    async def _on_envelope(self, envelope: Envelope) -> None:
        """Route incoming envelopes to appropriate handlers."""
        # Skip our own messages
        if envelope.from_agent == self.agent_id:
            return

        if envelope.topic == Topics.TICK:
            self._tick = envelope.tick
            await self.on_tick(envelope.tick)
        else:
            await self.on_market_message(
                envelope.topic,
                envelope.message,
                envelope.from_agent,
            )

    async def run(self, *, until_tick: int | None = None) -> None:
        """Run the agent event loop.

        Args:
            until_tick: If set, stop after reaching this tick number.
        """
        self._running = True
        logger.info("%s running (until_tick=%s)", self.agent_id, until_tick)

        try:
            while self._running:
                if until_tick is not None and self._tick >= until_tick:
                    logger.info("%s reached tick %d, stopping", self.agent_id, until_tick)
                    break
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("%s stopped", self.agent_id)

    def stop(self) -> None:
        """Stop the agent event loop."""
        self._running = False
