"""Tests for the TradingAgent SDK (external agent framework)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from streetmarket.agent.trading_agent import TradingAgent
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubAgent(TradingAgent):
    """Concrete subclass for testing — records ticks and messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ticks: list[int] = []
        self.messages: list[tuple[str, str, str]] = []

    async def on_tick(self, tick: int) -> None:
        self.ticks.append(tick)

    async def on_market_message(self, topic: str, message: str, from_agent: str) -> None:
        self.messages.append((topic, message, from_agent))


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


async def _fake_llm(system: str, context: str) -> str:
    return '{"action": "rest", "reason": "testing"}'


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestTradingAgentConstruction:
    def test_basic_construction(self):
        agent = TradingAgent(agent_id="baker-test", display_name="Test Baker")
        assert agent.agent_id == "baker-test"
        assert agent.display_name == "Test Baker"
        assert agent._llm is None

    def test_default_display_name_from_id(self):
        agent = TradingAgent(agent_id="baker-hugo")
        assert agent.display_name == "Baker Hugo"

    def test_injected_llm_fn(self):
        agent = TradingAgent(agent_id="t", llm_fn=_fake_llm)
        assert agent._llm is _fake_llm

    def test_initial_state(self):
        agent = TradingAgent(agent_id="t")
        assert agent.current_tick == 0
        assert not agent.is_connected
        assert not agent.is_joined

    def test_llm_config_creates_llm(self):
        """LLMConfig should create an LLM function via create_llm_fn."""
        with patch("streetmarket.agent.market_agent.create_llm_fn") as mock_create:
            mock_create.return_value = _fake_llm
            from streetmarket.agent.llm_config import LLMConfig

            config = LLMConfig(
                api_key="test-key",
                model="test-model",
                api_base="http://x",
                max_tokens=400,
                temperature=0.7,
            )
            agent = TradingAgent(agent_id="t", llm_config=config)
            assert agent._llm is _fake_llm
            mock_create.assert_called_once_with(config)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class TestConnection:
    @pytest.fixture
    def agent(self):
        return StubAgent(agent_id="test-agent", display_name="Test")

    async def test_connect_subscribes_to_all_topics(self, agent):
        mock_client = AsyncMock()
        with patch(
            "streetmarket.agent.trading_agent.MarketBusClient",
            return_value=mock_client,
        ):
            await agent.connect("nats://localhost:4222")

        assert agent.is_connected
        # Should subscribe to: tick, square, trades, bank, weather,
        # property, news, inbox = 8 topics
        assert mock_client.subscribe.call_count == 8

        subscribed_topics = [call.args[0] for call in mock_client.subscribe.call_args_list]
        assert Topics.TICK in subscribed_topics
        assert Topics.SQUARE in subscribed_topics
        assert Topics.TRADES in subscribed_topics
        assert Topics.BANK in subscribed_topics
        assert Topics.WEATHER in subscribed_topics
        assert Topics.PROPERTY in subscribed_topics
        assert Topics.NEWS in subscribed_topics
        assert Topics.agent_inbox("test-agent") in subscribed_topics

    async def test_disconnect(self, agent):
        mock_client = AsyncMock()
        with patch(
            "streetmarket.agent.trading_agent.MarketBusClient",
            return_value=mock_client,
        ):
            await agent.connect("nats://localhost:4222")
            await agent.disconnect()

        assert not agent.is_connected
        mock_client.close.assert_awaited_once()

    async def test_disconnect_without_connect(self, agent):
        # Should not raise
        await agent.disconnect()
        assert not agent.is_connected


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------


class TestJoining:
    async def test_join_sends_message_on_square(self):
        agent = StubAgent(agent_id="test-agent")
        mock_client = AsyncMock()
        with patch(
            "streetmarket.agent.trading_agent.MarketBusClient",
            return_value=mock_client,
        ):
            await agent.connect()
            await agent.join("Hello, I'm a baker!")

        assert agent.is_joined
        mock_client.publish.assert_awaited_once()
        call_args = mock_client.publish.call_args
        assert call_args.args[0] == Topics.SQUARE

    async def test_join_without_connect_raises(self):
        agent = StubAgent(agent_id="test-agent")
        with pytest.raises(RuntimeError, match="Not connected"):
            await agent.join("Hello!")


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------


class TestCommunication:
    @pytest.fixture
    async def connected_agent(self):
        agent = StubAgent(agent_id="test-agent", llm_fn=_fake_llm)
        mock_client = AsyncMock()
        with patch(
            "streetmarket.agent.trading_agent.MarketBusClient",
            return_value=mock_client,
        ):
            await agent.connect()
        agent._mock_client = mock_client
        return agent

    async def test_say(self, connected_agent):
        agent = connected_agent
        await agent.say(Topics.TRADES, "Selling bread!")
        agent._mock_client.publish.assert_awaited_once()
        topic, envelope = agent._mock_client.publish.call_args.args
        assert topic == Topics.TRADES
        assert envelope.message == "Selling bread!"
        assert envelope.from_agent == "test-agent"

    async def test_offer(self, connected_agent):
        agent = connected_agent
        await agent.offer("bread", 5, 3.0)
        agent._mock_client.publish.assert_awaited_once()
        topic, envelope = agent._mock_client.publish.call_args.args
        assert topic == Topics.TRADES
        assert "bread" in envelope.message.lower()
        assert "5" in envelope.message
        assert "3.0" in envelope.message

    async def test_bid(self, connected_agent):
        agent = connected_agent
        await agent.bid("potato", 10, 1.5)
        agent._mock_client.publish.assert_awaited_once()
        topic, envelope = agent._mock_client.publish.call_args.args
        assert topic == Topics.TRADES
        assert "potato" in envelope.message.lower()
        assert "10" in envelope.message

    async def test_ask_banker(self, connected_agent):
        agent = connected_agent
        await agent.ask_banker("What is my balance?")
        topic, envelope = agent._mock_client.publish.call_args.args
        assert topic == Topics.BANK
        assert "balance" in envelope.message.lower()

    async def test_ask_landlord(self, connected_agent):
        agent = connected_agent
        await agent.ask_landlord("Any properties for rent?")
        topic, envelope = agent._mock_client.publish.call_args.args
        assert topic == Topics.PROPERTY
        assert "properties" in envelope.message.lower()

    async def test_say_without_connect_raises(self):
        agent = StubAgent(agent_id="test-agent")
        with pytest.raises(RuntimeError, match="Not connected"):
            await agent.say(Topics.SQUARE, "Hello")


# ---------------------------------------------------------------------------
# LLM Reasoning
# ---------------------------------------------------------------------------


class TestLLMReasoning:
    async def test_think_returns_text(self):
        agent = TradingAgent(agent_id="t", llm_fn=_fake_llm)
        result = await agent.think("System prompt", "Context")
        assert '"action"' in result
        assert '"rest"' in result

    async def test_think_json_returns_dict(self):
        agent = TradingAgent(agent_id="t", llm_fn=_fake_llm)
        result = await agent.think_json("System prompt", "Context")
        assert result == {"action": "rest", "reason": "testing"}

    async def test_think_without_llm_returns_empty(self):
        agent = TradingAgent(agent_id="t")
        result = await agent.think("System prompt", "Context")
        assert result == ""

    async def test_think_json_without_llm_returns_empty_dict(self):
        agent = TradingAgent(agent_id="t")
        result = await agent.think_json("System prompt", "Context")
        assert result == {}

    async def test_think_handles_llm_error(self):
        async def _broken_llm(s, c):
            raise RuntimeError("LLM down")

        agent = TradingAgent(agent_id="t", llm_fn=_broken_llm)
        result = await agent.think("System", "Context")
        assert result == ""

    async def test_think_json_handles_non_json(self):
        async def _text_llm(s, c):
            return "I think we should rest for now."

        agent = TradingAgent(agent_id="t", llm_fn=_text_llm)
        result = await agent.think_json("System", "Context")
        assert result == {}


# ---------------------------------------------------------------------------
# Envelope Routing
# ---------------------------------------------------------------------------


class TestEnvelopeRouting:
    def _make_agent(self):
        return StubAgent(agent_id="test-agent")

    async def test_tick_updates_current_tick(self):
        agent = self._make_agent()
        envelope = _make_envelope(from_agent="system", topic=Topics.TICK, tick=42)
        await agent._on_envelope(envelope)
        assert agent.current_tick == 42
        assert agent.ticks == [42]

    async def test_market_message_routed(self):
        agent = self._make_agent()
        envelope = _make_envelope(
            from_agent="banker",
            topic=Topics.BANK,
            message="Your balance is 100 coins.",
            tick=5,
        )
        await agent._on_envelope(envelope)
        assert len(agent.messages) == 1
        assert agent.messages[0] == (
            Topics.BANK,
            "Your balance is 100 coins.",
            "banker",
        )

    async def test_own_messages_skipped(self):
        agent = self._make_agent()
        envelope = _make_envelope(
            from_agent="test-agent",
            topic=Topics.SQUARE,
            message="My own message",
        )
        await agent._on_envelope(envelope)
        assert agent.ticks == []
        assert agent.messages == []

    async def test_multiple_messages_routed(self):
        agent = self._make_agent()
        for i in range(5):
            env = _make_envelope(
                from_agent=f"agent-{i}",
                topic=Topics.TRADES,
                message=f"Message {i}",
                tick=i,
            )
            await agent._on_envelope(env)
        assert len(agent.messages) == 5

    async def test_inbox_message_routed(self):
        agent = self._make_agent()
        inbox_topic = Topics.agent_inbox("test-agent")
        envelope = _make_envelope(
            from_agent="governor",
            topic=inbox_topic,
            message="Welcome to the market!",
        )
        await agent._on_envelope(envelope)
        assert len(agent.messages) == 1
        assert agent.messages[0][2] == "governor"


# ---------------------------------------------------------------------------
# Run Loop
# ---------------------------------------------------------------------------


class TestRunLoop:
    async def test_run_until_tick(self):
        agent = StubAgent(agent_id="test-agent")
        agent._tick = 10
        # Should exit immediately since tick >= until_tick
        await agent.run(until_tick=10)
        assert not agent._running

    async def test_run_stops_on_stop(self):
        agent = StubAgent(agent_id="test-agent")

        async def stop_after_delay():
            await asyncio.sleep(0.2)
            agent.stop()

        task = asyncio.create_task(stop_after_delay())
        await agent.run()
        await task
        assert not agent._running

    async def test_stop_method(self):
        agent = StubAgent(agent_id="test-agent")
        agent._running = True
        agent.stop()
        assert not agent._running


# ---------------------------------------------------------------------------
# Subclass Integration
# ---------------------------------------------------------------------------


class TestSubclassIntegration:
    async def test_stub_agent_records_ticks_and_messages(self):
        agent = StubAgent(agent_id="my-agent", display_name="My Agent")
        # Simulate ticks
        for tick in [1, 2, 3]:
            env = _make_envelope(from_agent="system", topic=Topics.TICK, tick=tick)
            await agent._on_envelope(env)

        assert agent.ticks == [1, 2, 3]
        assert agent.current_tick == 3

        # Simulate market message
        env = _make_envelope(
            from_agent="banker",
            topic=Topics.BANK,
            message="Balance: 50",
        )
        await agent._on_envelope(env)
        assert len(agent.messages) == 1

    async def test_agent_with_llm_decides(self):
        """Full flow: agent uses LLM to reason, then acts."""

        async def smart_llm(system, context):
            return '{"action": "offer", "item": "bread", "qty": 5}'

        agent = StubAgent(
            agent_id="baker-test",
            display_name="Test Baker",
            llm_fn=smart_llm,
        )
        decision = await agent.think_json("You are a baker.", "Tick 10.")
        assert decision["action"] == "offer"
        assert decision["item"] == "bread"


# ---------------------------------------------------------------------------
# Export checks
# ---------------------------------------------------------------------------


class TestExports:
    def test_trading_agent_importable_from_agent_package(self):
        from streetmarket.agent import TradingAgent as TA

        assert TA is TradingAgent

    def test_trading_agent_importable_from_top_level(self):
        from streetmarket import TradingAgent as TA

        assert TA is TradingAgent
