"""ManagedAgent — platform-hosted agent using shared LLM key.

Extends TradingAgent with:
- Shared LLM via LLMConfig.for_service("managed") — no user API key needed
- Tick throttle — only calls LLM every N ticks (saves cost)
- Recent market message context (last 10 messages)
- Runtime stats tracking (ticks, messages, LLM calls)
- Structured on_tick decision-making via think_json

Usage:
    agent = create_managed_agent(
        agent_id="managed-a1b2c3d4",
        display_name="Hugo's Bakery",
        system_prompt="You are a baker...",
        tick_interval=3,
    )
    await agent.connect("nats://localhost:4222")
    await agent.join("I am Hugo's Bakery!")
    await agent.run()
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from streetmarket.agent.llm_config import LLMConfig
from streetmarket.agent.trading_agent import LLMFunction, TradingAgent
from streetmarket.models.topics import Topics

logger = logging.getLogger(__name__)

# Maximum recent messages to keep for LLM context
MAX_CONTEXT_MESSAGES = 10


@dataclass
class ManagedAgentStats:
    """Runtime stats tracked by the managed agent."""

    ticks_active: int = 0
    messages_sent: int = 0
    llm_calls: int = 0
    last_active_tick: int = 0


@dataclass
class ManagedAgentConfig:
    """Configuration passed to a ManagedAgent instance."""

    agent_id: str
    display_name: str
    system_prompt: str
    tick_interval: int = 3
    archetype: str = "custom"
    personality: str = ""
    strategy: str = ""
    model_override: str | None = None


class ManagedAgent(TradingAgent):
    """Platform-hosted agent with shared LLM and tick throttle.

    Key differences from TradingAgent:
    - Uses shared platform LLM key (LLMConfig.for_service("managed"))
    - Only calls LLM every N ticks (tick_interval) to save cost
    - Builds context from recent market messages
    - Tracks runtime statistics
    """

    def __init__(
        self,
        *,
        config: ManagedAgentConfig,
        llm_fn: LLMFunction | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        super().__init__(
            agent_id=config.agent_id,
            display_name=config.display_name,
            llm_fn=llm_fn,
            llm_config=llm_config,
        )
        self._config = config
        self._system_prompt = config.system_prompt
        self._tick_interval = config.tick_interval
        self._recent_messages: deque[dict[str, str]] = deque(maxlen=MAX_CONTEXT_MESSAGES)
        self._stats = ManagedAgentStats()

    @property
    def stats(self) -> ManagedAgentStats:
        return self._stats

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tick_interval(self) -> int:
        return self._tick_interval

    # -- Event Handlers --

    async def on_tick(self, tick: int) -> None:
        """Called every tick. Only calls LLM every N ticks."""
        self._stats.ticks_active += 1
        self._stats.last_active_tick = tick

        # Throttle: only decide on tick_interval boundaries
        if tick % self._tick_interval != 0:
            return

        # Build context from recent messages
        context = self._build_context(tick)

        # Ask LLM for a decision
        decision = await self.think_json(self._system_prompt, context)
        if decision:
            self._stats.llm_calls += 1
            await self._execute_decision(decision)

    async def on_market_message(self, topic: str, message: str, from_agent: str) -> None:
        """Record market messages for context. React to direct inbox messages."""
        self._recent_messages.append({"topic": topic, "from": from_agent, "message": message})

        # React immediately to direct inbox messages
        if topic == Topics.agent_inbox(self.agent_id):
            context = (
                f"You received a direct message from {from_agent}:\n"
                f'"{message}"\n\n'
                f"Current tick: {self.current_tick}\n"
                f"Respond appropriately."
            )
            decision = await self.think_json(self._system_prompt, context)
            if decision:
                self._stats.llm_calls += 1
                await self._execute_decision(decision)

    # -- Internal --

    def _build_context(self, tick: int) -> str:
        """Build LLM context from recent market activity."""
        parts = [f"Current tick: {tick}"]

        if self._recent_messages:
            parts.append("\nRecent market activity:")
            for msg in self._recent_messages:
                parts.append(f"  [{msg['topic']}] {msg['from']}: {msg['message']}")
        else:
            parts.append("\nNo recent market activity observed.")

        parts.append(
            "\nDecide your next action. Respond with JSON:\n"
            '{"action": "offer|bid|say|think|rest", '
            '"topic": "/market/trades or /market/square", '
            '"message": "your natural language message", '
            '"item": "item name (for offer/bid)", '
            '"quantity": 1, "price": 10.0}'
        )

        return "\n".join(parts)

    async def _execute_decision(self, decision: dict[str, Any]) -> None:
        """Execute an LLM decision."""
        action = decision.get("action", "rest")

        try:
            if action == "offer":
                item = decision.get("item", "goods")
                qty = int(decision.get("quantity", 1))
                price = float(decision.get("price", 1.0))
                await self.offer(item, qty, price)
                self._stats.messages_sent += 1

            elif action == "bid":
                item = decision.get("item", "goods")
                qty = int(decision.get("quantity", 1))
                price = float(decision.get("price", 1.0))
                await self.bid(item, qty, price)
                self._stats.messages_sent += 1

            elif action == "say":
                topic = decision.get("topic", Topics.SQUARE)
                message = decision.get("message", "")
                if message:
                    await self.say(topic, message)
                    self._stats.messages_sent += 1

            elif action == "think":
                message = decision.get("message", "")
                if message:
                    await self.share_thought(message)
                    self._stats.messages_sent += 1

            elif action == "rest":
                pass  # Do nothing this tick

            else:
                logger.warning("%s: Unknown action '%s' — resting", self.agent_id, action)

        except Exception:
            logger.exception("%s: Failed to execute action '%s'", self.agent_id, action)


def create_managed_agent(
    *,
    agent_id: str,
    display_name: str,
    system_prompt: str,
    tick_interval: int = 3,
    archetype: str = "custom",
    personality: str = "",
    strategy: str = "",
    llm_fn: LLMFunction | None = None,
    model_override: str | None = None,
) -> ManagedAgent:
    """Factory function to create a ManagedAgent.

    Uses LLMConfig.for_service("managed") for shared platform LLM key,
    unless llm_fn is provided (for testing).
    """
    config = ManagedAgentConfig(
        agent_id=agent_id,
        display_name=display_name,
        system_prompt=system_prompt,
        tick_interval=tick_interval,
        archetype=archetype,
        personality=personality,
        strategy=strategy,
        model_override=model_override,
    )

    llm_config = None
    if llm_fn is None:
        llm_config = LLMConfig.for_service("managed")

    return ManagedAgent(
        config=config,
        llm_fn=llm_fn,
        llm_config=llm_config,
    )
