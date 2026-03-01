"""Tests for the ManagedAgent class."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from streetmarket.agent.managed_agent import (
    ManagedAgent,
    ManagedAgentConfig,
    create_managed_agent,
)
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ManagedAgentConfig:
    defaults = {
        "agent_id": "managed-test1234",
        "display_name": "Test Baker",
        "system_prompt": "You are a test baker.",
        "tick_interval": 3,
        "archetype": "baker",
    }
    defaults.update(overrides)
    return ManagedAgentConfig(**defaults)


async def _fake_llm_rest(system: str, context: str) -> str:
    return '{"action": "rest"}'


async def _fake_llm_offer(system: str, context: str) -> str:
    return '{"action": "offer", "item": "bread", "quantity": 5, "price": 3.0}'


async def _fake_llm_say(system: str, context: str) -> str:
    return '{"action": "say", "topic": "/market/square", "message": "Hello market!"}'


async def _fake_llm_think(system: str, context: str) -> str:
    return '{"action": "think", "message": "I should buy flour"}'


async def _fake_llm_bid(system: str, context: str) -> str:
    return '{"action": "bid", "item": "flour", "quantity": 10, "price": 2.0}'


def _make_envelope(
    *,
    from_agent: str = "other-agent",
    topic: str = Topics.SQUARE,
    message: str = "hello",
    tick: int = 1,
) -> Envelope:
    return Envelope(
        from_agent=from_agent,
        topic=topic,
        message=message,
        tick=tick,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestManagedAgentConstruction:
    def test_basic_construction(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        assert agent.agent_id == "managed-test1234"
        assert agent.display_name == "Test Baker"
        assert agent.system_prompt == "You are a test baker."
        assert agent.tick_interval == 3

    def test_stats_initialized(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        assert agent.stats.ticks_active == 0
        assert agent.stats.messages_sent == 0
        assert agent.stats.llm_calls == 0


# ---------------------------------------------------------------------------
# Tick Throttle
# ---------------------------------------------------------------------------


class TestTickThrottle:
    @pytest.mark.asyncio
    async def test_only_calls_llm_on_interval(self):
        config = _make_config(tick_interval=3)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)

        # Mock publish to avoid NATS
        agent._client = AsyncMock()

        # Ticks 1, 2 should not call LLM
        await agent.on_tick(1)
        await agent.on_tick(2)
        assert agent.stats.llm_calls == 0

        # Tick 3 should call LLM (3 % 3 == 0)
        await agent.on_tick(3)
        assert agent.stats.llm_calls == 1

        # Tick 6 should call again
        await agent.on_tick(6)
        assert agent.stats.llm_calls == 2

    @pytest.mark.asyncio
    async def test_tick_0_calls_llm(self):
        """Tick 0 should trigger LLM (0 % N == 0)."""
        config = _make_config(tick_interval=5)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        agent._client = AsyncMock()

        await agent.on_tick(0)
        assert agent.stats.llm_calls == 1

    @pytest.mark.asyncio
    async def test_ticks_active_increments_every_tick(self):
        config = _make_config(tick_interval=3)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        await agent.on_tick(2)
        await agent.on_tick(3)
        assert agent.stats.ticks_active == 3


# ---------------------------------------------------------------------------
# Decision Execution
# ---------------------------------------------------------------------------


class TestDecisionExecution:
    @pytest.mark.asyncio
    async def test_offer_action(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_offer)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.messages_sent == 1
        assert agent.stats.llm_calls == 1

    @pytest.mark.asyncio
    async def test_bid_action(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_bid)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.messages_sent == 1

    @pytest.mark.asyncio
    async def test_say_action(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_say)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.messages_sent == 1

    @pytest.mark.asyncio
    async def test_think_action(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_think)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.messages_sent == 1

    @pytest.mark.asyncio
    async def test_rest_action_sends_nothing(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.messages_sent == 0

    @pytest.mark.asyncio
    async def test_no_llm_no_action(self):
        config = _make_config(tick_interval=1)
        agent = ManagedAgent(config=config)
        agent._client = AsyncMock()

        await agent.on_tick(1)
        assert agent.stats.llm_calls == 0
        assert agent.stats.messages_sent == 0


# ---------------------------------------------------------------------------
# Market Message Handling
# ---------------------------------------------------------------------------


class TestMarketMessageHandling:
    @pytest.mark.asyncio
    async def test_records_market_messages(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        agent._client = AsyncMock()

        await agent.on_market_message(Topics.SQUARE, "Hello!", "governor")
        await agent.on_market_message(Topics.TRADES, "Selling bread", "baker-1")

        assert len(agent._recent_messages) == 2
        assert agent._recent_messages[0]["from"] == "governor"
        assert agent._recent_messages[1]["from"] == "baker-1"

    @pytest.mark.asyncio
    async def test_inbox_message_triggers_immediate_response(self):
        config = _make_config(agent_id="managed-inbox")
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_say)
        agent._client = AsyncMock()

        inbox = Topics.agent_inbox("managed-inbox")
        await agent.on_market_message(inbox, "Hey there!", "governor")

        assert agent.stats.llm_calls == 1

    @pytest.mark.asyncio
    async def test_context_capped_at_max(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)

        for i in range(15):
            await agent.on_market_message(Topics.SQUARE, f"msg {i}", f"agent-{i}")

        # Should be capped at MAX_CONTEXT_MESSAGES (10)
        assert len(agent._recent_messages) == 10


# ---------------------------------------------------------------------------
# Context Building
# ---------------------------------------------------------------------------


class TestContextBuilding:
    def test_context_includes_tick(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)

        context = agent._build_context(42)
        assert "Current tick: 42" in context

    def test_context_includes_messages(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)
        agent._recent_messages.append(
            {"topic": "/market/square", "from": "baker-1", "message": "Fresh bread!"}
        )

        context = agent._build_context(1)
        assert "Fresh bread!" in context
        assert "baker-1" in context

    def test_context_with_no_messages(self):
        config = _make_config()
        agent = ManagedAgent(config=config, llm_fn=_fake_llm_rest)

        context = agent._build_context(1)
        assert "No recent market activity" in context


# ---------------------------------------------------------------------------
# Factory Function
# ---------------------------------------------------------------------------


class TestCreateManagedAgent:
    @patch.dict(
        "os.environ",
        {
            "OPENROUTER_API_KEY": "test-key",
            "DEFAULT_MODEL": "test-model",
        },
    )
    def test_factory_creates_agent_with_llm_config(self):
        agent = create_managed_agent(
            agent_id="managed-factory",
            display_name="Factory Agent",
            system_prompt="You are a test.",
        )
        assert agent.agent_id == "managed-factory"
        assert agent._llm is not None

    def test_factory_with_injected_llm(self):
        agent = create_managed_agent(
            agent_id="managed-injected",
            display_name="Injected Agent",
            system_prompt="You are a test.",
            llm_fn=_fake_llm_rest,
        )
        assert agent.agent_id == "managed-injected"
        assert agent._llm is _fake_llm_rest
