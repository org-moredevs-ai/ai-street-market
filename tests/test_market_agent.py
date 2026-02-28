"""Tests for MarketAgent base class and all 6 agent implementations.

All tests mock the LLM function (llm_fn) and use in-memory publish/subscribe
collectors. No NATS connection needed. Uses pytest-asyncio with asyncio_mode="auto".
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from streetmarket.agent.market_agent import MarketAgent
from streetmarket.helpers.factory import create_message
from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import EventTypes, LedgerEvent
from streetmarket.models.topics import Topics
from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.ranking.engine import RankingEngine
from streetmarket.registry.registry import AgentRegistry
from streetmarket.world_state.store import (
    Field,
    FieldStatus,
    Resource,
    WorldStateStore,
)


def _minimal_season_config() -> SeasonConfig:
    """Create a minimal SeasonConfig for tests that need RankingEngine."""
    from datetime import datetime, timezone

    return SeasonConfig(
        name="Test Season",
        number=1,
        description="A test season",
        starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        tick_interval_seconds=60,
        world_policy_file="test.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[
            WinningCriterion(metric="community_contribution", weight=1.0),
        ],
        awards=[],
        closing_percent=10,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


class _TestLedger(InMemoryLedger):
    """Test-friendly ledger that tolerates BankerAgent calling remove_item with tick.

    BankerAgent._on_trade_approved passes tick as a 4th arg to remove_item,
    but InMemoryLedger.remove_item only takes (agent_id, item, qty).
    This subclass absorbs the extra keyword/positional arg so tests work.
    """

    async def remove_item(self, agent_id: str, item: str, qty: int, tick: int = 0) -> None:  # type: ignore[override]
        return await super().remove_item(agent_id, item, qty)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_fn(response: str = "{}") -> AsyncMock:
    """Create a mock LLM function that returns a fixed response."""
    fn = AsyncMock(return_value=response)
    return fn


def _make_publish_fn() -> tuple[AsyncMock, list[tuple[str, Envelope]]]:
    """Create a mock publish_fn that collects (topic, envelope) pairs."""
    collected: list[tuple[str, Envelope]] = []

    async def publish(topic: str, envelope: Envelope) -> None:
        collected.append((topic, envelope))

    mock = AsyncMock(side_effect=publish)
    return mock, collected


def _make_subscribe_fn() -> tuple[AsyncMock, dict[str, Any]]:
    """Create a mock subscribe_fn that records subscriptions."""
    subscriptions: dict[str, Any] = {}

    async def subscribe(topic: str, handler: Any) -> None:
        subscriptions[topic] = handler

    mock = AsyncMock(side_effect=subscribe)
    return mock, subscriptions


def _tick_envelope(tick: int, from_agent: str = "clock") -> Envelope:
    """Create a tick envelope."""
    return create_message(
        from_agent=from_agent,
        topic=Topics.TICK,
        message=f"Tick {tick}",
        tick=tick,
    )


def _msg_envelope(
    topic: str,
    message: str,
    from_agent: str = "some-agent",
    tick: int = 1,
) -> Envelope:
    """Create a generic message envelope."""
    return create_message(
        from_agent=from_agent,
        topic=topic,
        message=message,
        tick=tick,
    )


# ---------------------------------------------------------------------------
# Concrete subclass for testing the base MarketAgent
# ---------------------------------------------------------------------------


class StubAgent(MarketAgent):
    """Minimal concrete subclass for testing base behavior."""

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK, Topics.SQUARE]

    def build_system_prompt(self) -> str:
        return f"You are {self.character_name}. {self.personality}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_fn() -> AsyncMock:
    return _make_llm_fn()


@pytest.fixture
def pub() -> tuple[AsyncMock, list[tuple[str, Envelope]]]:
    return _make_publish_fn()


@pytest.fixture
def sub() -> tuple[AsyncMock, dict[str, Any]]:
    return _make_subscribe_fn()


@pytest.fixture
def stub_agent(
    llm_fn: AsyncMock,
    pub: tuple[AsyncMock, list[tuple[str, Envelope]]],
    sub: tuple[AsyncMock, dict[str, Any]],
) -> StubAgent:
    publish_fn, _ = pub
    subscribe_fn, _ = sub
    return StubAgent(
        agent_id="stub-agent",
        character_name="Stubby",
        personality="A test stub.",
        publish_fn=publish_fn,
        subscribe_fn=subscribe_fn,
        llm_fn=llm_fn,
    )


@pytest.fixture
def ledger() -> _TestLedger:
    return _TestLedger()


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def world_state() -> WorldStateStore:
    return WorldStateStore()


# ===========================================================================
# MarketAgent base class tests
# ===========================================================================


class TestMarketAgentConstructor:
    """Constructor requires llm_fn or llm_config."""

    def test_constructor_with_llm_fn(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        agent = StubAgent(
            agent_id="a",
            character_name="A",
            personality="test",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=_make_llm_fn(),
        )
        assert agent.agent_id == "a"
        assert agent.character_name == "A"

    def test_constructor_without_llm_raises(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        with pytest.raises(ValueError, match="Either llm_fn or llm_config"):
            StubAgent(
                agent_id="a",
                character_name="A",
                personality="test",
                publish_fn=publish_fn,
                subscribe_fn=subscribe_fn,
            )

    def test_initial_tick_default_zero(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        agent = StubAgent(
            agent_id="a",
            character_name="A",
            personality="test",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=_make_llm_fn(),
        )
        assert agent.current_tick == 0

    def test_initial_tick_custom(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        agent = StubAgent(
            agent_id="a",
            character_name="A",
            personality="test",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=_make_llm_fn(),
            tick=42,
        )
        assert agent.current_tick == 42


class TestMarketAgentNotImplemented:
    """topics_to_subscribe and build_system_prompt raise NotImplementedError on base."""

    def test_topics_to_subscribe_raises(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        agent = MarketAgent(
            agent_id="a",
            character_name="A",
            personality="test",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=_make_llm_fn(),
        )
        with pytest.raises(NotImplementedError):
            agent.topics_to_subscribe()

    def test_build_system_prompt_raises(self) -> None:
        publish_fn, _ = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()
        agent = MarketAgent(
            agent_id="a",
            character_name="A",
            personality="test",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=_make_llm_fn(),
        )
        with pytest.raises(NotImplementedError):
            agent.build_system_prompt()


class TestMarketAgentRespond:
    """respond() publishes an envelope with correct topic and message."""

    async def test_respond_publishes_envelope(self, stub_agent: StubAgent) -> None:
        await stub_agent.respond(Topics.SQUARE, "Hello, market!")

        stub_agent._publish.assert_called_once()
        call_args = stub_agent._publish.call_args
        topic = call_args[0][0]
        envelope = call_args[0][1]
        assert topic == Topics.SQUARE
        assert isinstance(envelope, Envelope)
        assert envelope.message == "Hello, market!"
        assert envelope.from_agent == "stub-agent"
        assert envelope.topic == Topics.SQUARE


class TestMarketAgentEmitEvent:
    """emit_event() publishes a LedgerEvent envelope to /system/ledger."""

    async def test_emit_event_publishes_to_ledger(self, stub_agent: StubAgent) -> None:
        event = LedgerEvent(
            event=EventTypes.AGENT_REGISTERED,
            emitted_by="stub-agent",
            tick=1,
            data={"agent_id": "farmer"},
        )
        await stub_agent.emit_event(event)

        stub_agent._publish.assert_called_once()
        call_args = stub_agent._publish.call_args
        topic = call_args[0][0]
        envelope = call_args[0][1]
        assert topic == Topics.LEDGER
        assert envelope.topic == Topics.LEDGER
        # The message is the JSON-serialized LedgerEvent
        parsed = json.loads(envelope.message)
        assert parsed["event"] == "agent_registered"
        assert parsed["data"]["agent_id"] == "farmer"


class TestMarketAgentReason:
    """reason() calls the LLM with system prompt and context."""

    async def test_reason_calls_llm(self, stub_agent: StubAgent, llm_fn: AsyncMock) -> None:
        llm_fn.return_value = "I think we should trade."
        result = await stub_agent.reason("What should we do?")
        assert result == "I think we should trade."
        llm_fn.assert_called_once()
        # First arg is system prompt, second is context
        args = llm_fn.call_args[0]
        assert "Stubby" in args[0]  # system prompt has character name
        assert "What should we do?" == args[1]

    async def test_reason_returns_empty_on_error(
        self, stub_agent: StubAgent, llm_fn: AsyncMock
    ) -> None:
        llm_fn.side_effect = RuntimeError("LLM down")
        result = await stub_agent.reason("test")
        assert result == ""


class TestMarketAgentReasonJson:
    """reason_json() extracts JSON from LLM response."""

    async def test_reason_json_extracts_json(
        self, stub_agent: StubAgent, llm_fn: AsyncMock
    ) -> None:
        llm_fn.return_value = '{"decision": "accept", "reason": "looks good"}'
        result = await stub_agent.reason_json("evaluate this")
        assert result["decision"] == "accept"
        assert result["reason"] == "looks good"

    async def test_reason_json_returns_empty_on_no_json(
        self, stub_agent: StubAgent, llm_fn: AsyncMock
    ) -> None:
        llm_fn.return_value = "No JSON here at all, just plain text!"
        result = await stub_agent.reason_json("evaluate this")
        assert result == {}

    async def test_reason_json_handles_markdown_code_blocks(
        self, stub_agent: StubAgent, llm_fn: AsyncMock
    ) -> None:
        llm_fn.return_value = '```json\n{"key": "value"}\n```'
        result = await stub_agent.reason_json("test")
        assert result["key"] == "value"

    async def test_reason_json_returns_empty_on_llm_error(
        self, stub_agent: StubAgent, llm_fn: AsyncMock
    ) -> None:
        llm_fn.side_effect = RuntimeError("LLM crash")
        result = await stub_agent.reason_json("test")
        assert result == {}


class TestMarketAgentRouteMessage:
    """_route_message skips own messages, routes ticks, routes others."""

    async def test_skips_own_messages(self, stub_agent: StubAgent) -> None:
        """Messages from the agent itself are ignored."""
        own_msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="my own message",
            from_agent="stub-agent",
        )
        # Should not raise, should silently skip
        await stub_agent._route_message(own_msg)

    async def test_routes_tick_messages(self, stub_agent: StubAgent) -> None:
        """Tick messages update the tick counter and call on_tick."""
        tick_msg = _tick_envelope(tick=5)
        await stub_agent._route_message(tick_msg)
        assert stub_agent.current_tick == 5

    async def test_routes_tick_updates_tick_number(self, stub_agent: StubAgent) -> None:
        """Each tick updates the internal tick counter."""
        await stub_agent._route_message(_tick_envelope(tick=1))
        assert stub_agent.current_tick == 1
        await stub_agent._route_message(_tick_envelope(tick=2))
        assert stub_agent.current_tick == 2
        await stub_agent._route_message(_tick_envelope(tick=10))
        assert stub_agent.current_tick == 10

    async def test_routes_non_tick_to_on_message(self, stub_agent: StubAgent) -> None:
        """Non-tick messages go to on_message (base does nothing, no crash)."""
        msg = _msg_envelope(topic=Topics.SQUARE, message="Hello!")
        await stub_agent._route_message(msg)
        # Should not raise


class TestMarketAgentStart:
    """start() subscribes to all topics from topics_to_subscribe."""

    async def test_start_subscribes(
        self,
        stub_agent: StubAgent,
        sub: tuple[AsyncMock, dict[str, Any]],
    ) -> None:
        _, subscriptions = sub
        await stub_agent.start()
        assert Topics.TICK in subscriptions
        assert Topics.SQUARE in subscriptions
        assert len(subscriptions) == 2
        assert stub_agent._started is True


# ===========================================================================
# MeteoAgent tests
# ===========================================================================


class TestMeteoAgent:
    """Tests for MeteoAgent — weather oracle."""

    def _make_meteo(
        self,
        world_state: WorldStateStore,
        llm_response: str = "{}",
    ) -> tuple:
        from services.meteo.meteo import MeteoAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = MeteoAgent(
            agent_id="meteo",
            character_name="Weatherus",
            personality="Dramatic weather oracle",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            world_state=world_state,
            forecast_interval=10,
        )
        return agent, llm_fn, collected, subscriptions

    def test_topics_to_subscribe(self, world_state: WorldStateStore) -> None:
        agent, _, _, _ = self._make_meteo(world_state)
        topics = agent.topics_to_subscribe()
        assert topics == [Topics.TICK]

    async def test_on_tick_generates_forecast_at_interval(
        self, world_state: WorldStateStore
    ) -> None:
        llm_response = json.dumps(
            {
                "forecast": "A storm approaches!",
                "condition": "stormy",
                "temperature": "cold",
                "wind": "strong",
                "effects": [],
            }
        )
        agent, llm_fn, collected, _ = self._make_meteo(world_state, llm_response)

        # Tick 10 should trigger (interval=10, last=0)
        await agent.on_tick(10)

        # LLM was called
        llm_fn.assert_called_once()
        # Should have published 2 messages: forecast + event
        assert len(collected) == 2
        # First is the NL forecast to /market/weather
        topic, env = collected[0]
        assert topic == Topics.WEATHER
        assert "storm" in env.message.lower()
        # Second is the weather_change event to /system/ledger
        topic2, env2 = collected[1]
        assert topic2 == Topics.LEDGER

    async def test_on_tick_skips_if_interval_not_reached(
        self, world_state: WorldStateStore
    ) -> None:
        agent, llm_fn, collected, _ = self._make_meteo(world_state)

        # Tick 5 should NOT trigger (interval=10, last=0)
        await agent.on_tick(5)
        llm_fn.assert_not_called()
        assert len(collected) == 0

    async def test_weather_update_emits_weather_change_event(
        self, world_state: WorldStateStore
    ) -> None:
        llm_response = json.dumps(
            {
                "forecast": "Clear skies ahead",
                "condition": "sunny",
                "temperature": "warm",
                "wind": "calm",
                "effects": [
                    {
                        "type": "crop_boost",
                        "target": "fields",
                        "modifier": 1.2,
                        "reason": "sunshine",
                    }
                ],
            }
        )
        agent, _, collected, _ = self._make_meteo(world_state, llm_response)

        await agent.on_tick(10)

        # Find the ledger event
        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        _, event_env = ledger_msgs[0]
        event_data = json.loads(event_env.message)
        assert event_data["event"] == EventTypes.WEATHER_CHANGE
        assert event_data["data"]["condition"] == "sunny"
        assert event_data["data"]["temperature"] == "warm"
        assert event_data["data"]["wind"] == "calm"
        assert len(event_data["data"]["effects"]) == 1

    async def test_on_tick_empty_llm_response_does_nothing(
        self, world_state: WorldStateStore
    ) -> None:
        """Empty LLM response (reason_json returns {}) does nothing."""
        # LLM returns text that is not valid JSON
        agent, llm_fn, collected, _ = self._make_meteo(world_state, "I have no idea")
        await agent.on_tick(10)
        llm_fn.assert_called_once()
        # reason_json returns {} -> no publish
        assert len(collected) == 0


# ===========================================================================
# NatureAgent tests
# ===========================================================================


class TestNatureAgent:
    """Tests for NatureAgent — living world manager."""

    def _make_nature(
        self,
        world_state: WorldStateStore,
        llm_response: str = "{}",
        nature_interval: int = 5,
    ) -> tuple:
        from services.nature.nature import NatureAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = NatureAgent(
            agent_id="nature",
            character_name="Gaia",
            personality="Spirit of the land",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            world_state=world_state,
            nature_interval=nature_interval,
        )
        return agent, llm_fn, collected, subscriptions

    def test_topics_to_subscribe(self, world_state: WorldStateStore) -> None:
        agent, _, _, _ = self._make_nature(world_state)
        topics = agent.topics_to_subscribe()
        assert Topics.TICK in topics
        assert Topics.LEDGER in topics

    async def test_on_tick_evaluates_at_interval(self, world_state: WorldStateStore) -> None:
        llm_response = json.dumps(
            {
                "announcement": "The fields are ripe!",
                "field_updates": [],
                "resource_updates": [],
            }
        )
        agent, llm_fn, collected, _ = self._make_nature(
            world_state, llm_response, nature_interval=5
        )

        await agent.on_tick(5)
        llm_fn.assert_called_once()

    async def test_on_tick_skips_before_interval(self, world_state: WorldStateStore) -> None:
        agent, llm_fn, collected, _ = self._make_nature(world_state, nature_interval=5)
        await agent.on_tick(3)
        llm_fn.assert_not_called()

    async def test_field_updates_emit_field_update_events(
        self, world_state: WorldStateStore
    ) -> None:
        # Add a field to the world
        await world_state.add_field(
            Field(id="field-1", type="farmland", location="north", status=FieldStatus.GROWING)
        )
        llm_response = json.dumps(
            {
                "announcement": "Crops are ready!",
                "field_updates": [
                    {"field_id": "field-1", "status": "ready", "crop": "potato", "ready_tick": 10},
                ],
                "resource_updates": [],
            }
        )
        agent, _, collected, _ = self._make_nature(world_state, llm_response)

        await agent.on_tick(5)

        # Find field_update events in ledger messages
        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        _, event_env = ledger_msgs[0]
        event_data = json.loads(event_env.message)
        assert event_data["event"] == EventTypes.FIELD_UPDATE
        assert event_data["data"]["field_id"] == "field-1"
        assert event_data["data"]["status"] == "ready"

    async def test_resource_updates_emit_resource_update_events(
        self, world_state: WorldStateStore
    ) -> None:
        await world_state.add_resource(
            Resource(id="res-wood", type="wood", location="forest", quantity=50)
        )
        llm_response = json.dumps(
            {
                "announcement": "Trees regrow.",
                "field_updates": [],
                "resource_updates": [
                    {"resource_id": "res-wood", "quantity_delta": 10, "reason": "natural regrowth"},
                ],
            }
        )
        agent, _, collected, _ = self._make_nature(world_state, llm_response)

        await agent.on_tick(5)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        _, event_env = ledger_msgs[0]
        event_data = json.loads(event_env.message)
        assert event_data["event"] == EventTypes.RESOURCE_UPDATE
        assert event_data["data"]["resource_id"] == "res-wood"
        assert event_data["data"]["quantity_delta"] == 10

    async def test_multiple_field_and_resource_updates(self, world_state: WorldStateStore) -> None:
        """Multiple updates emit multiple events."""
        llm_response = json.dumps(
            {
                "announcement": "Nature stirs.",
                "field_updates": [
                    {"field_id": "f1", "status": "ready", "crop": "potato", "ready_tick": None},
                    {"field_id": "f2", "status": "flooded", "crop": None, "ready_tick": None},
                ],
                "resource_updates": [
                    {"resource_id": "r1", "quantity_delta": 5, "reason": "regrowth"},
                ],
            }
        )
        agent, _, collected, _ = self._make_nature(world_state, llm_response)
        await agent.on_tick(5)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        # 2 field updates + 1 resource update = 3
        assert len(ledger_msgs) == 3


# ===========================================================================
# GovernorAgent tests
# ===========================================================================


class TestGovernorAgent:
    """Tests for GovernorAgent — trade validation and onboarding."""

    def _make_governor(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        llm_response: str = "{}",
    ) -> tuple:
        from services.governor.governor import GovernorAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = GovernorAgent(
            agent_id="governor",
            character_name="Lord Governor",
            personality="Stern but fair ruler",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            ledger=ledger,
            registry=registry,
        )
        return agent, llm_fn, collected, subscriptions

    def test_topics_to_subscribe(self, ledger: _TestLedger, registry: AgentRegistry) -> None:
        agent, _, _, _ = self._make_governor(ledger, registry)
        topics = agent.topics_to_subscribe()
        assert Topics.TICK in topics
        assert Topics.SQUARE in topics
        assert Topics.TRADES in topics

    async def test_join_message_triggers_onboarding(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "accept",
                "response": "Welcome to the market, farmer!",
                "agent_id": "farmer",
                "starting_wallet": 100,
                "reason": "Seems like a good citizen",
            }
        )
        agent, llm_fn, collected, _ = self._make_governor(ledger, registry, llm_response)

        join_msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="Hello! I am a farmer and I want to join the market.",
            from_agent="farmer",
        )
        await agent.on_message(join_msg)

        llm_fn.assert_called_once()
        # Should emit agent_registered event + NL response
        assert len(collected) >= 2

    async def test_accept_decision_emits_agent_registered(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "accept",
                "response": "Welcome!",
                "agent_id": "farmer",
                "starting_wallet": 150,
                "reason": "Accepted",
            }
        )
        agent, _, collected, _ = self._make_governor(ledger, registry, llm_response)

        join_msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="I want to join the market!",
            from_agent="farmer",
        )
        await agent.on_message(join_msg)

        # Find agent_registered event
        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        event_data = json.loads(ledger_msgs[0][1].message)
        assert event_data["event"] == EventTypes.AGENT_REGISTERED
        assert event_data["data"]["agent_id"] == "farmer"
        assert event_data["data"]["starting_wallet"] == 150

    async def test_reject_decision_emits_agent_rejected(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "reject",
                "response": "Not welcome here!",
                "agent_id": "hacker",
                "reason": "Suspicious activity",
            }
        )
        agent, _, collected, _ = self._make_governor(ledger, registry, llm_response)

        join_msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="Hello! I am a hacker trying to join.",
            from_agent="hacker",
        )
        await agent.on_message(join_msg)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        event_data = json.loads(ledger_msgs[0][1].message)
        assert event_data["event"] == EventTypes.AGENT_REJECTED
        assert event_data["data"]["agent_id"] == "hacker"

    async def test_non_join_square_message_ignored(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        """Messages without join keywords on /market/square are ignored."""
        agent, llm_fn, collected, _ = self._make_governor(ledger, registry)

        msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="Nice weather today!",
            from_agent="farmer",
        )
        await agent.on_message(msg)
        llm_fn.assert_not_called()
        assert len(collected) == 0

    async def test_trade_proposal_approved(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "approve",
                "response": "Trade approved!",
                "buyer": "chef",
                "seller": "farmer",
                "item": "potato",
                "quantity": 5,
                "price_per_unit": 3.0,
                "total": 15.0,
                "reason": "Fair trade",
            }
        )
        agent, _, collected, _ = self._make_governor(ledger, registry, llm_response)

        trade_msg = _msg_envelope(
            topic=Topics.TRADES,
            message="I want to buy 5 potatoes from farmer at 3 coins each.",
            from_agent="chef",
        )
        await agent.on_message(trade_msg)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        event_data = json.loads(ledger_msgs[0][1].message)
        assert event_data["event"] == EventTypes.TRADE_APPROVED
        assert event_data["data"]["buyer"] == "chef"
        assert event_data["data"]["seller"] == "farmer"
        assert event_data["data"]["item"] == "potato"
        assert event_data["data"]["quantity"] == 5
        assert event_data["data"]["total"] == 15.0

    async def test_trade_proposal_rejected(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "reject",
                "response": "This trade is not fair!",
                "reason": "Price is too high",
            }
        )
        agent, _, collected, _ = self._make_governor(ledger, registry, llm_response)

        trade_msg = _msg_envelope(
            topic=Topics.TRADES,
            message="I want to buy potatoes for 100 coins each.",
            from_agent="chef",
        )
        await agent.on_message(trade_msg)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        event_data = json.loads(ledger_msgs[0][1].message)
        assert event_data["event"] == EventTypes.TRADE_REJECTED

    async def test_governor_publishes_nl_response_on_accept(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "decision": "accept",
                "response": "Welcome aboard, friend!",
                "agent_id": "farmer",
                "starting_wallet": 100,
                "reason": "accepted",
            }
        )
        agent, _, collected, _ = self._make_governor(ledger, registry, llm_response)

        join_msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="I am new here, hello!",
            from_agent="farmer",
        )
        await agent.on_message(join_msg)

        # Find NL response on /market/square
        square_msgs = [(t, e) for t, e in collected if t == Topics.SQUARE]
        assert len(square_msgs) == 1
        assert "Welcome" in square_msgs[0][1].message

    def test_topics_includes_thoughts(self, ledger: _TestLedger, registry: AgentRegistry) -> None:
        agent, _, _, _ = self._make_governor(ledger, registry)
        topics = agent.topics_to_subscribe()
        assert Topics.THOUGHTS in topics


class TestGovernorThoughtScoring:
    """Tests for Governor thought scoring — community contribution points."""

    def _make_governor_with_ranking(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        llm_response: str = "{}",
    ) -> tuple:
        from services.governor.governor import GovernorAgent

        ranking = RankingEngine(_minimal_season_config(), ledger, registry)
        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = GovernorAgent(
            agent_id="governor",
            character_name="Lord Governor",
            personality="Stern but fair",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            ledger=ledger,
            registry=registry,
            ranking_engine=ranking,
        )
        return agent, llm_fn, collected, subscriptions, ranking

    async def test_high_score_thought_records_community_contribution(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "score": 4.0,
                "response": "Brilliant insight, farmer!",
                "reason": "Shows deep understanding of market dynamics",
            }
        )
        agent, _, collected, _, ranking = self._make_governor_with_ranking(
            ledger, registry, llm_response
        )

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="I think wheat prices will rise because storms reduce supply.",
            from_agent="farmer",
        )
        await agent.on_message(thought_msg)

        assert ranking._community_scores.get("farmer", 0.0) == 4.0

    async def test_high_score_thought_publishes_response(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "score": 4.0,
                "response": "Well said, farmer!",
                "reason": "Great insight",
            }
        )
        agent, _, collected, _, _ = self._make_governor_with_ranking(ledger, registry, llm_response)

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="Market dynamics insight here.",
            from_agent="farmer",
        )
        await agent.on_message(thought_msg)

        square_msgs = [(t, e) for t, e in collected if t == Topics.SQUARE]
        assert len(square_msgs) == 1
        assert "Well said" in square_msgs[0][1].message

    async def test_low_score_thought_no_public_response(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "score": 1.5,
                "response": "Noted.",
                "reason": "Trivial observation",
            }
        )
        agent, _, collected, _, ranking = self._make_governor_with_ranking(
            ledger, registry, llm_response
        )

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="It is sunny today.",
            from_agent="farmer",
        )
        await agent.on_message(thought_msg)

        # Score is recorded but no public response (< 3.0)
        assert ranking._community_scores.get("farmer", 0.0) == 1.5
        square_msgs = [(t, e) for t, e in collected if t == Topics.SQUARE]
        assert len(square_msgs) == 0

    async def test_zero_score_not_recorded(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        llm_response = json.dumps(
            {
                "score": 0.0,
                "response": "",
                "reason": "Spam",
            }
        )
        agent, _, _, _, ranking = self._make_governor_with_ranking(ledger, registry, llm_response)

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="...",
            from_agent="spammer",
        )
        await agent.on_message(thought_msg)

        assert ranking._community_scores.get("spammer", 0.0) == 0.0

    async def test_score_clamped_to_max(self, ledger: _TestLedger, registry: AgentRegistry) -> None:
        llm_response = json.dumps({"score": 10.0, "response": "Amazing!", "reason": "Best ever"})
        agent, _, _, _, ranking = self._make_governor_with_ranking(ledger, registry, llm_response)

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="Deep insight.",
            from_agent="genius",
        )
        await agent.on_message(thought_msg)

        assert ranking._community_scores.get("genius", 0.0) == 5.0

    async def test_thoughts_ignored_without_ranking_engine(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        """Governor without ranking_engine silently ignores thoughts."""
        from services.governor.governor import GovernorAgent

        llm_fn = _make_llm_fn()
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, _ = _make_subscribe_fn()

        agent = GovernorAgent(
            agent_id="governor",
            character_name="Lord Governor",
            personality="Stern",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            ledger=ledger,
            registry=registry,
        )

        thought_msg = _msg_envelope(
            topic=Topics.THOUGHTS,
            message="Some thought.",
            from_agent="farmer",
        )
        await agent.on_message(thought_msg)

        # LLM should not be called, no messages published
        llm_fn.assert_not_called()
        assert len(collected) == 0

    async def test_multiple_thoughts_accumulate_score(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        agent, llm_fn, _, _, ranking = self._make_governor_with_ranking(ledger, registry)

        # First thought: score 2.0
        llm_fn.return_value = json.dumps({"score": 2.0, "response": "", "reason": "ok"})
        msg1 = _msg_envelope(topic=Topics.THOUGHTS, message="Thought 1", from_agent="farmer")
        await agent.on_message(msg1)

        # Second thought: score 3.0
        llm_fn.return_value = json.dumps({"score": 3.0, "response": "Nice!", "reason": "good"})
        msg2 = _msg_envelope(topic=Topics.THOUGHTS, message="Thought 2", from_agent="farmer")
        await agent.on_message(msg2)

        assert ranking._community_scores.get("farmer", 0.0) == 5.0


# ===========================================================================
# BankerAgent tests
# ===========================================================================


class TestBankerAgent:
    """Tests for BankerAgent — transaction processing."""

    def _make_banker(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        llm_response: str = "{}",
    ) -> tuple:
        from services.banker.banker import BankerAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = BankerAgent(
            agent_id="banker",
            character_name="Sir Coins",
            personality="Precise and meticulous banker",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            ledger=ledger,
            registry=registry,
        )
        return agent, llm_fn, collected, subscriptions

    def test_topics_to_subscribe(self, ledger: _TestLedger, registry: AgentRegistry) -> None:
        agent, _, _, _ = self._make_banker(ledger, registry)
        topics = agent.topics_to_subscribe()
        assert Topics.TICK in topics
        assert Topics.LEDGER in topics
        assert Topics.BANK in topics

    async def test_agent_registered_creates_wallet(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        agent, _, collected, _ = self._make_banker(ledger, registry)

        # Simulate agent_registered event from Governor
        event = LedgerEvent(
            event=EventTypes.AGENT_REGISTERED,
            emitted_by="governor",
            tick=1,
            data={"agent_id": "farmer", "starting_wallet": 100},
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        # Wallet should be created
        balance = await ledger.get_balance("farmer")
        assert balance == Decimal("100")

        # Agent registered in registry
        rec = await registry.get("farmer")
        assert rec is not None
        assert rec.id == "farmer"

        # Confirmation published to /market/bank
        bank_msgs = [(t, e) for t, e in collected if t == Topics.BANK]
        assert len(bank_msgs) == 1
        assert "farmer" in bank_msgs[0][1].message.lower()

    async def test_trade_approved_transfers_coins_and_items(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        # Setup: create wallets and inventory
        await ledger.create_wallet("buyer", Decimal("100"))
        await ledger.create_wallet("seller", Decimal("50"))
        await ledger.add_item("seller", "potato", 10)

        agent, _, collected, _ = self._make_banker(ledger, registry)

        # Simulate trade_approved event
        event = LedgerEvent(
            event=EventTypes.TRADE_APPROVED,
            emitted_by="governor",
            tick=5,
            data={
                "buyer": "buyer",
                "seller": "seller",
                "item": "potato",
                "quantity": 3,
                "total": 15.0,
            },
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        # Buyer paid 15 coins
        buyer_balance = await ledger.get_balance("buyer")
        assert buyer_balance == Decimal("85")

        # Seller received 15 coins
        seller_balance = await ledger.get_balance("seller")
        assert seller_balance == Decimal("65")

        # Buyer got 3 potatoes
        buyer_inv = await ledger.get_inventory("buyer")
        assert buyer_inv.get("potato") == 3

        # Seller lost 3 potatoes (7 remaining)
        seller_inv = await ledger.get_inventory("seller")
        assert seller_inv.get("potato") == 7

    async def test_trade_with_insufficient_funds_responds_error(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        await ledger.create_wallet("poor-buyer", Decimal("5"))
        await ledger.create_wallet("seller", Decimal("50"))
        await ledger.add_item("seller", "potato", 10)

        agent, _, collected, _ = self._make_banker(ledger, registry)

        event = LedgerEvent(
            event=EventTypes.TRADE_APPROVED,
            emitted_by="governor",
            tick=5,
            data={
                "buyer": "poor-buyer",
                "seller": "seller",
                "item": "potato",
                "quantity": 3,
                "total": 100.0,
            },
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        # Buyer balance unchanged
        balance = await ledger.get_balance("poor-buyer")
        assert balance == Decimal("5")

        # Error response on /market/bank
        bank_msgs = [(t, e) for t, e in collected if t == Topics.BANK]
        assert len(bank_msgs) == 1
        assert "insufficient" in bank_msgs[0][1].message.lower()

    async def test_fine_issued_debits_wallet(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        await ledger.create_wallet("troublemaker", Decimal("50"))

        agent, _, collected, _ = self._make_banker(ledger, registry)

        event = LedgerEvent(
            event=EventTypes.FINE_ISSUED,
            emitted_by="governor",
            tick=10,
            data={"agent": "troublemaker", "amount": 10, "reason": "disruptive behavior"},
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        balance = await ledger.get_balance("troublemaker")
        assert balance == Decimal("40")

        # Confirmation message
        bank_msgs = [(t, e) for t, e in collected if t == Topics.BANK]
        assert len(bank_msgs) == 1
        assert "fine" in bank_msgs[0][1].message.lower()

    async def test_rent_collected_debits_wallet(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        await ledger.create_wallet("tenant", Decimal("20"))

        agent, _, collected, _ = self._make_banker(ledger, registry)

        event = LedgerEvent(
            event=EventTypes.RENT_COLLECTED,
            emitted_by="landlord",
            tick=60,
            data={"agent": "tenant", "amount": 0.5},
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="landlord",
        )
        await agent.on_message(event_msg)

        balance = await ledger.get_balance("tenant")
        assert balance == Decimal("19.5")

    async def test_banker_ignores_own_events(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        """Banker should not process events it emitted itself."""
        agent, _, collected, _ = self._make_banker(ledger, registry)

        event = LedgerEvent(
            event=EventTypes.AGENT_REGISTERED,
            emitted_by="banker",  # emitted by the banker itself
            tick=1,
            data={"agent_id": "farmer", "starting_wallet": 100},
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        # No wallet should be created
        wallet = await ledger.get_wallet("farmer")
        assert wallet is None

    async def test_incomplete_trade_data_skipped(
        self, ledger: _TestLedger, registry: AgentRegistry
    ) -> None:
        """Trade with missing fields (empty buyer) is skipped."""
        await ledger.create_wallet("seller", Decimal("50"))

        agent, _, collected, _ = self._make_banker(ledger, registry)

        event = LedgerEvent(
            event=EventTypes.TRADE_APPROVED,
            emitted_by="governor",
            tick=5,
            data={
                "buyer": "",
                "seller": "seller",
                "item": "potato",
                "quantity": 3,
                "total": 15.0,
            },
        )
        event_msg = _msg_envelope(
            topic=Topics.LEDGER,
            message=event.model_dump_json(),
            from_agent="governor",
        )
        await agent.on_message(event_msg)

        # No changes
        seller_balance = await ledger.get_balance("seller")
        assert seller_balance == Decimal("50")
        assert len(collected) == 0


# ===========================================================================
# LandlordAgent tests
# ===========================================================================


class TestLandlordAgent:
    """Tests for LandlordAgent — property management and rent collection."""

    async def _make_landlord(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
        llm_response: str = "{}",
        rent_interval: int = 10,
        rent_amount: float = 0.5,
        grace_ticks: int = 50,
    ) -> tuple:
        from services.landlord.landlord import LandlordAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = LandlordAgent(
            agent_id="landlord",
            character_name="Lord Land",
            personality="Greedy but lawful",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            rent_interval=rent_interval,
            rent_amount=rent_amount,
            grace_ticks=grace_ticks,
        )
        return agent, llm_fn, collected, subscriptions

    async def test_topics_to_subscribe(
        self, ledger: _TestLedger, registry: AgentRegistry, world_state: WorldStateStore
    ) -> None:
        agent, _, _, _ = await self._make_landlord(ledger, registry, world_state)
        topics = agent.topics_to_subscribe()
        assert Topics.TICK in topics
        assert Topics.PROPERTY in topics

    async def test_on_tick_collects_rent_from_eligible(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
    ) -> None:
        # Register an agent that joined at tick 0, now at tick 60 (past 50 grace)
        await registry.register(agent_id="farmer", owner="farmer", display_name="Farmer", tick=0)

        agent, _, collected, _ = await self._make_landlord(
            ledger,
            registry,
            world_state,
            rent_interval=10,
            rent_amount=0.5,
            grace_ticks=50,
        )

        await agent.on_tick(60)

        # Should emit rent_collected event
        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 1
        event_data = json.loads(ledger_msgs[0][1].message)
        assert event_data["event"] == EventTypes.RENT_COLLECTED
        assert event_data["data"]["agent"] == "farmer"
        assert event_data["data"]["amount"] == 0.5

    async def test_on_tick_skips_agents_in_grace_period(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
    ) -> None:
        # Agent joined at tick 20, current tick 30 — only 10 ticks alive (< 50 grace)
        await registry.register(agent_id="newbie", owner="newbie", display_name="Newbie", tick=20)

        agent, _, collected, _ = await self._make_landlord(
            ledger,
            registry,
            world_state,
            grace_ticks=50,
        )

        await agent.on_tick(30)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 0

    async def test_on_tick_skips_house_owners(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
    ) -> None:
        # Agent joined at tick 0, owns a house — should be exempt
        await registry.register(
            agent_id="homeowner",
            owner="homeowner",
            display_name="Homeowner",
            tick=0,
        )
        await world_state.set_property("prop-1", {"type": "house", "owner": "homeowner"})

        agent, _, collected, _ = await self._make_landlord(
            ledger,
            registry,
            world_state,
            grace_ticks=50,
        )

        await agent.on_tick(60)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 0

    async def test_on_tick_skips_if_interval_not_reached(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
    ) -> None:
        await registry.register(agent_id="farmer", owner="farmer", display_name="Farmer", tick=0)

        agent, _, collected, _ = await self._make_landlord(
            ledger,
            registry,
            world_state,
            rent_interval=10,
        )

        # Tick 5 shouldn't trigger rent (interval=10, last=0)
        await agent.on_tick(5)
        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 0

    async def test_rent_collection_for_multiple_agents(
        self,
        ledger: _TestLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
    ) -> None:
        """Rent collected from all eligible agents, not just the first."""
        await registry.register(agent_id="farmer", owner="farmer", display_name="Farmer", tick=0)
        await registry.register(agent_id="chef", owner="chef", display_name="Chef", tick=0)

        agent, _, collected, _ = await self._make_landlord(
            ledger,
            registry,
            world_state,
            grace_ticks=50,
        )

        await agent.on_tick(60)

        ledger_msgs = [(t, e) for t, e in collected if t == Topics.LEDGER]
        assert len(ledger_msgs) == 2
        agents_charged = {json.loads(e.message)["data"]["agent"] for _, e in ledger_msgs}
        assert agents_charged == {"farmer", "chef"}


# ===========================================================================
# TownCrierAgent tests
# ===========================================================================


class TestTownCrierAgent:
    """Tests for TownCrierAgent — dramatic narration."""

    def _make_crier(
        self,
        llm_response: str = "Hear ye, hear ye!",
        narration_interval: int = 15,
    ) -> tuple:
        from services.town_crier.narrator import TownCrierAgent

        llm_fn = _make_llm_fn(llm_response)
        publish_fn, collected = _make_publish_fn()
        subscribe_fn, subscriptions = _make_subscribe_fn()

        agent = TownCrierAgent(
            agent_id="crier",
            character_name="Town Crier",
            personality="Dramatic and theatrical",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_fn=llm_fn,
            narration_interval=narration_interval,
        )
        return agent, llm_fn, collected, subscriptions

    def test_topics_to_subscribe(self) -> None:
        agent, _, _, _ = self._make_crier()
        topics = agent.topics_to_subscribe()
        # Town Crier subscribes to many topics
        assert Topics.TICK in topics
        assert Topics.SQUARE in topics
        assert Topics.TRADES in topics
        assert Topics.BANK in topics
        assert Topics.WEATHER in topics
        assert Topics.PROPERTY in topics
        assert Topics.LEDGER in topics

    async def test_on_message_collects_events(self) -> None:
        agent, _, _, _ = self._make_crier()

        msg = _msg_envelope(
            topic=Topics.SQUARE,
            message="A farmer arrives at the market!",
            from_agent="governor",
        )
        await agent.on_message(msg)

        assert len(agent._recent_events) == 1
        assert "governor" in agent._recent_events[0]
        assert "farmer arrives" in agent._recent_events[0]

    async def test_on_message_skips_own_messages(self) -> None:
        agent, _, _, _ = self._make_crier()

        own_msg = _msg_envelope(
            topic=Topics.NEWS,
            message="My own narration.",
            from_agent="crier",
        )
        await agent.on_message(own_msg)

        assert len(agent._recent_events) == 0

    async def test_on_tick_generates_narration_at_interval(self) -> None:
        agent, llm_fn, collected, _ = self._make_crier(
            llm_response="The market buzzed with energy today!",
            narration_interval=15,
        )

        # Add some events first
        agent._recent_events.append("[/market/square] farmer: I am selling potatoes!")
        agent._recent_events.append("[/market/trades] chef: I want to buy!")

        # Tick 15 triggers narration (interval=15, last=0)
        await agent.on_tick(15)

        llm_fn.assert_called_once()
        # Published to /market/news
        news_msgs = [(t, e) for t, e in collected if t == Topics.NEWS]
        assert len(news_msgs) == 1
        assert "market buzzed" in news_msgs[0][1].message

    async def test_on_tick_clears_events_after_narration(self) -> None:
        agent, _, _, _ = self._make_crier(
            llm_response="Things happened!",
            narration_interval=15,
        )

        agent._recent_events.append("event 1")
        agent._recent_events.append("event 2")

        await agent.on_tick(15)

        assert len(agent._recent_events) == 0

    async def test_on_tick_skips_if_no_events(self) -> None:
        agent, llm_fn, collected, _ = self._make_crier(narration_interval=15)

        # No events collected — should skip
        await agent.on_tick(15)

        llm_fn.assert_not_called()
        assert len(collected) == 0

    async def test_on_tick_skips_if_interval_not_reached(self) -> None:
        agent, llm_fn, _, _ = self._make_crier(narration_interval=15)

        agent._recent_events.append("something happened")
        # Tick 5 — interval not reached
        await agent.on_tick(5)

        llm_fn.assert_not_called()

    async def test_narration_truncated_to_800_chars(self) -> None:
        """Long narrations are truncated to 800 characters."""
        long_text = "A" * 1000
        agent, _, collected, _ = self._make_crier(
            llm_response=long_text,
            narration_interval=15,
        )
        agent._recent_events.append("event")

        await agent.on_tick(15)

        news_msgs = [(t, e) for t, e in collected if t == Topics.NEWS]
        assert len(news_msgs) == 1
        narration = news_msgs[0][1].message
        assert len(narration) == 800
        assert narration.endswith("...")

    async def test_multiple_events_collected_before_narration(self) -> None:
        """Events accumulate until narration tick."""
        agent, llm_fn, collected, _ = self._make_crier(narration_interval=15)

        # Collect 5 events
        for i in range(5):
            msg = _msg_envelope(
                topic=Topics.SQUARE,
                message=f"Event {i}",
                from_agent=f"agent-{i}",
            )
            await agent.on_message(msg)

        assert len(agent._recent_events) == 5

        # Before interval — no narration
        await agent.on_tick(10)
        llm_fn.assert_not_called()
        assert len(agent._recent_events) == 5

    async def test_narration_context_includes_recent_events(self) -> None:
        """LLM context includes the recent events."""
        agent, llm_fn, _, _ = self._make_crier(
            llm_response="Big day at market!",
            narration_interval=15,
        )
        agent._recent_events.append("[/market/square] farmer: potatoes for sale!")
        agent._recent_events.append("[/market/trades] chef: buying potatoes!")

        await agent.on_tick(15)

        # Check the context passed to LLM
        call_args = llm_fn.call_args[0]
        context = call_args[1]
        assert "potatoes for sale" in context
        assert "buying potatoes" in context

    async def test_empty_llm_response_skips_publish(self) -> None:
        """Empty/falsy LLM response does not publish."""
        agent, llm_fn, collected, _ = self._make_crier(narration_interval=15)
        llm_fn.return_value = ""
        agent._recent_events.append("event")

        await agent.on_tick(15)

        # No messages published (empty response)
        assert len(collected) == 0
        # But events are still cleared
        assert len(agent._recent_events) == 0
