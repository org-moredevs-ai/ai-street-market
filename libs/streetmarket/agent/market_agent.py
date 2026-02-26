"""MarketAgent — base class for LLM-powered market infrastructure agents.

Each market agent (Governor, Banker, Nature, Meteo, Landlord, Town Crier)
inherits from this base. The base provides:
- NATS subscription and message routing
- LLM reasoning with personality and context injection
- Structured event emission to /system/ledger
- Natural language response publishing

The LLM function is injectable for testing (pass llm_fn to constructor).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from streetmarket.agent.llm_brain import extract_json
from streetmarket.agent.llm_config import LLMConfig
from streetmarket.helpers.factory import create_message
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import LedgerEvent
from streetmarket.models.topics import Topics

logger = logging.getLogger(__name__)

# Type for the LLM callable: takes system_prompt + user_message, returns text
LLMFunction = Callable[[str, str], Coroutine[Any, Any, str]]

# Type for the publish function
PublishFunction = Callable[[str, Envelope], Coroutine[Any, Any, None]]

# Type for the subscribe function
SubscribeFunction = Callable[
    [str, Callable[[Envelope], Coroutine[Any, Any, None]]],
    Coroutine[Any, Any, None],
]


def create_llm_fn(config: LLMConfig) -> LLMFunction:
    """Create an LLM callable from config using LangChain + OpenRouter."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    )

    async def call_llm(system_prompt: str, user_message: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    return call_llm


class MarketAgent:
    """Base class for market infrastructure agents.

    Subclasses implement:
    - topics_to_subscribe: which NATS topics to listen on
    - build_system_prompt: personality + context for the LLM
    - on_tick: called every tick
    - on_message: called for each incoming message

    The base handles subscription routing, LLM invocation, and event emission.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        character_name: str,
        personality: str,
        publish_fn: PublishFunction,
        subscribe_fn: SubscribeFunction,
        llm_fn: LLMFunction | None = None,
        llm_config: LLMConfig | None = None,
        tick: int = 0,
    ) -> None:
        self.agent_id = agent_id
        self.character_name = character_name
        self.personality = personality
        self._publish = publish_fn
        self._subscribe = subscribe_fn
        self._tick = tick
        self._started = False

        # LLM function: injected for tests, or created from config
        if llm_fn is not None:
            self._llm = llm_fn
        elif llm_config is not None:
            self._llm = create_llm_fn(llm_config)
        else:
            raise ValueError("Either llm_fn or llm_config must be provided")

    @property
    def current_tick(self) -> int:
        return self._tick

    async def start(self) -> None:
        """Subscribe to relevant topics and start processing."""
        topics = self.topics_to_subscribe()
        for topic in topics:
            await self._subscribe(topic, self._route_message)
        self._started = True
        logger.info(
            "%s (%s) started, subscribed to %d topics",
            self.character_name,
            self.agent_id,
            len(topics),
        )

    def topics_to_subscribe(self) -> list[str]:
        """Return list of NATS topics this agent listens on.

        Subclasses must override.
        """
        raise NotImplementedError

    def build_system_prompt(self) -> str:
        """Build the LLM system prompt with personality and context.

        Subclasses must override.
        """
        raise NotImplementedError

    async def on_tick(self, tick: int) -> None:
        """Called on each tick. Subclasses override for periodic work."""

    async def on_message(self, envelope: Envelope) -> None:
        """Called for each incoming message. Subclasses override."""

    async def _route_message(self, envelope: Envelope) -> None:
        """Route incoming messages to tick handler or message handler."""
        # Don't process our own messages
        if envelope.from_agent == self.agent_id:
            return

        if envelope.topic == Topics.TICK:
            self._tick = envelope.tick
            await self.on_tick(envelope.tick)
        else:
            await self.on_message(envelope)

    async def reason(self, context: str) -> str:
        """Ask the LLM to reason about a situation.

        Args:
            context: The situation/message to reason about.

        Returns:
            Raw LLM text response.
        """
        system_prompt = self.build_system_prompt()
        try:
            response = await self._llm(system_prompt, context)
            return response
        except Exception:
            logger.exception("%s: LLM reasoning failed", self.agent_id)
            return ""

    async def reason_json(self, context: str) -> dict[str, Any]:
        """Ask the LLM to reason and return structured JSON.

        Uses extract_json to parse the response.
        """
        raw = await self.reason(context)
        if not raw:
            return {}
        try:
            return extract_json(raw)
        except ValueError:
            logger.warning(
                "%s: Could not extract JSON from LLM response: %s",
                self.agent_id,
                raw[:200],
            )
            return {}

    async def respond(self, topic: str, message: str) -> None:
        """Publish a natural language response to a topic."""
        envelope = create_message(
            from_agent=self.agent_id,
            topic=topic,
            message=message,
            tick=self._tick,
        )
        await self._publish(topic, envelope)
        logger.debug("%s -> %s: %s", self.agent_id, topic, message[:100])

    async def emit_event(self, event: LedgerEvent) -> None:
        """Emit a structured event to /system/ledger."""
        event_envelope = create_message(
            from_agent=self.agent_id,
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            tick=self._tick,
        )
        await self._publish(Topics.LEDGER, event_envelope)
        logger.debug(
            "%s emitted event: %s",
            self.agent_id,
            event.event,
        )

    def _make_event(self, event_type: str, data: dict[str, Any]) -> LedgerEvent:
        """Helper to create a LedgerEvent."""
        return LedgerEvent(
            event=event_type,
            emitted_by=self.agent_id,
            tick=self._tick,
            data=data,
        )
