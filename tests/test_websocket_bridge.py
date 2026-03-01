"""Tests for the WebSocket bridge service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics
from streetmarket.policy.engine import SeasonConfig
from streetmarket.registry import AgentRegistry, Profile
from streetmarket.season import SeasonManager, SeasonPhase
from streetmarket.world_state import Building, Field, FieldStatus, Weather, WorldStateStore

from services.websocket_bridge.bridge import (
    MAX_HISTORY,
    WebSocketBridge,
    _envelope_to_dict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    *,
    from_agent: str = "farmer",
    topic: str = Topics.TRADES,
    message: str = "Selling 5 potatoes!",
    tick: int = 10,
) -> Envelope:
    return Envelope(
        from_agent=from_agent,
        topic=topic,
        message=message,
        tick=tick,
    )


def _make_bridge(**kwargs) -> WebSocketBridge:
    """Create a bridge with no NATS connection."""
    return WebSocketBridge(
        nats_url="nats://localhost:4222",
        ws_host="localhost",
        ws_port=0,
        **kwargs,
    )


def _make_season_config() -> SeasonConfig:
    """Create a minimal SeasonConfig for testing."""
    from datetime import datetime, timezone

    from streetmarket.policy.engine import WinningCriterion

    return SeasonConfig(
        name="Harvest Festival",
        number=1,
        description="The first season",
        starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc),
        tick_interval_seconds=10,
        world_policy_file="earth-medieval-temperate.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.5),
            WinningCriterion(metric="survival_ticks", weight=0.5),
        ],
        awards=[],
        closing_percent=20,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


class FakeWS:
    """Fake WebSocket connection for testing broadcast."""

    def __init__(self, *, closed: bool = False):
        self.sent: list[str] = []
        self._closed = closed
        self.remote_address = ("127.0.0.1", 12345)

    async def send(self, data: str) -> None:
        if self._closed:
            import websockets

            raise websockets.exceptions.ConnectionClosed(None, None)
        self.sent.append(data)


# ---------------------------------------------------------------------------
# Envelope conversion
# ---------------------------------------------------------------------------


class TestEnvelopeToDict:
    def test_converts_all_fields(self):
        env = _make_envelope(
            from_agent="baker",
            topic=Topics.SQUARE,
            message="Hello market!",
            tick=42,
        )
        result = _envelope_to_dict(env)
        assert result["from"] == "baker"
        assert result["topic"] == Topics.SQUARE
        assert result["message"] == "Hello market!"
        assert result["tick"] == 42
        assert "id" in result
        assert "timestamp" in result

    def test_uses_from_not_from_agent(self):
        """Viewer-facing dict should use 'from' key, matching the protocol."""
        env = _make_envelope(from_agent="governor")
        result = _envelope_to_dict(env)
        assert "from" in result
        assert "from_agent" not in result


# ---------------------------------------------------------------------------
# Bridge construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self):
        bridge = _make_bridge()
        assert bridge.client_count == 0
        assert bridge.current_tick == 0

    def test_with_components(self):
        registry = AgentRegistry()
        world = WorldStateStore()
        bridge = _make_bridge(
            registry=registry,
            world_state=world,
        )
        assert bridge._registry is registry
        assert bridge._world_state is world


# ---------------------------------------------------------------------------
# NATS message handling
# ---------------------------------------------------------------------------


class TestNATSHandlers:
    async def test_on_tick_updates_current_tick(self):
        bridge = _make_bridge()
        env = _make_envelope(
            from_agent="system",
            topic=Topics.TICK,
            tick=99,
        )
        await bridge._on_tick(env)
        assert bridge.current_tick == 99

    async def test_on_nats_message_adds_to_history(self):
        bridge = _make_bridge()
        env = _make_envelope(message="Fresh bread!")
        await bridge._on_nats_message(env)
        assert len(bridge._history) == 1
        assert bridge._history[0]["message"] == "Fresh bread!"

    async def test_on_nats_message_broadcasts_to_clients(self):
        bridge = _make_bridge()
        client = FakeWS()
        bridge._clients.add(client)

        env = _make_envelope(message="Potatoes for sale!")
        await bridge._on_nats_message(env)

        assert len(client.sent) == 1
        data = json.loads(client.sent[0])
        assert data["type"] == "message"
        assert data["data"]["message"] == "Potatoes for sale!"

    async def test_history_capped_at_max(self):
        bridge = _make_bridge()
        for i in range(MAX_HISTORY + 50):
            env = _make_envelope(message=f"Message {i}", tick=i)
            await bridge._on_nats_message(env)
        assert len(bridge._history) == MAX_HISTORY

    async def test_broadcast_removes_dead_clients(self):
        bridge = _make_bridge()
        alive = FakeWS()
        dead = FakeWS(closed=True)
        bridge._clients.add(alive)
        bridge._clients.add(dead)

        env = _make_envelope()
        await bridge._on_nats_message(env)

        # Dead client removed, alive client kept
        assert alive in bridge._clients
        assert dead not in bridge._clients
        assert len(alive.sent) == 1


# ---------------------------------------------------------------------------
# State snapshots
# ---------------------------------------------------------------------------


class TestStateSnapshots:
    def test_minimal_snapshot(self):
        bridge = _make_bridge()
        bridge._current_tick = 42
        snapshot = bridge._build_state_snapshot()
        assert snapshot["tick"] == 42
        assert "timestamp" in snapshot

    async def test_snapshot_with_registry(self):
        registry = AgentRegistry()
        await registry.register(
            agent_id="baker-hugo",
            owner="hugo",
            display_name="Hugo's Bakery",
            profile=Profile(description="Fresh bread daily"),
        )
        bridge = _make_bridge(registry=registry)
        snapshot = bridge._build_state_snapshot()
        assert len(snapshot["agents"]) == 1
        agent = snapshot["agents"][0]
        assert agent["agent_id"] == "baker-hugo"
        assert agent["display_name"] == "Hugo's Bakery"
        assert agent["state"] == "active"
        assert agent["description"] == "Fresh bread daily"

    async def test_snapshot_with_world_state(self):
        world = WorldStateStore()
        await world.set_weather(
            Weather(
                condition="sunny",
                temperature="warm",
                wind="light",
                temperature_celsius=22,
            )
        )
        bridge = _make_bridge(world_state=world)
        snapshot = bridge._build_state_snapshot()
        assert snapshot["weather"]["condition"] == "sunny"
        assert snapshot["weather"]["temperature"] == "warm"
        assert snapshot["weather"]["wind"] == "light"
        assert snapshot["weather"]["temperature_celsius"] == 22
        assert snapshot["weather"]["temperature_fahrenheit"] == 72

    async def test_snapshot_weather_without_celsius(self):
        """When temperature_celsius is None, neither C nor F appear in snapshot."""
        world = WorldStateStore()
        await world.set_weather(
            Weather(condition="cloudy", temperature="cool", wind="moderate")
        )
        bridge = _make_bridge(world_state=world)
        snapshot = bridge._build_state_snapshot()
        assert "temperature_celsius" not in snapshot["weather"]
        assert "temperature_fahrenheit" not in snapshot["weather"]

    async def test_snapshot_with_fields(self):
        world = WorldStateStore()
        await world.add_field(
            Field(
                id="field-1",
                type="farmland",
                location="north",
                crop="potato",
                status=FieldStatus.GROWING,
                owner="farmer-a",
            )
        )
        bridge = _make_bridge(world_state=world)
        snapshot = bridge._build_state_snapshot()
        assert len(snapshot["fields"]) == 1
        assert snapshot["fields"][0]["crop"] == "potato"
        assert snapshot["fields"][0]["field_id"] == "field-1"
        assert snapshot["fields"][0]["status"] == "growing"

    async def test_snapshot_with_buildings(self):
        world = WorldStateStore()
        await world.add_building(
            Building(
                id="house-1",
                type="house",
                owner="baker-hugo",
            )
        )
        bridge = _make_bridge(world_state=world)
        snapshot = bridge._build_state_snapshot()
        assert len(snapshot["buildings"]) == 1
        assert snapshot["buildings"][0]["building_id"] == "house-1"
        assert snapshot["buildings"][0]["building_type"] == "house"
        assert snapshot["buildings"][0]["owner"] == "baker-hugo"

    def test_snapshot_with_season(self):
        config = _make_season_config()
        season = SeasonManager(config)
        season.advance_to(SeasonPhase.OPEN)
        bridge = _make_bridge(season_manager=season)
        snapshot = bridge._build_state_snapshot()
        assert snapshot["season"]["name"] == "Harvest Festival"
        assert snapshot["season"]["phase"] == "open"
        assert isinstance(snapshot["season"]["progress"], float)

    async def test_broadcast_state(self):
        bridge = _make_bridge()
        bridge._current_tick = 50
        client = FakeWS()
        bridge._clients.add(client)

        await bridge.broadcast_state()

        assert len(client.sent) == 1
        data = json.loads(client.sent[0])
        assert data["type"] == "state"
        assert data["data"]["tick"] == 50


# ---------------------------------------------------------------------------
# Multiple messages
# ---------------------------------------------------------------------------


class TestMultipleMessages:
    async def test_multiple_topics_forwarded(self):
        bridge = _make_bridge()
        client = FakeWS()
        bridge._clients.add(client)

        topics_and_messages = [
            (Topics.SQUARE, "farmer", "Hello market!"),
            (Topics.TRADES, "baker", "Selling bread at 5 coins"),
            (Topics.BANK, "banker", "Balance: 100 coins"),
            (Topics.WEATHER, "meteo", "Sunny with light breeze"),
            (Topics.NEWS, "town-crier", "The great baker has arrived!"),
        ]

        for topic, agent, msg in topics_and_messages:
            env = _make_envelope(from_agent=agent, topic=topic, message=msg)
            await bridge._on_nats_message(env)

        assert len(client.sent) == 5
        messages = [json.loads(s) for s in client.sent]
        topics_received = [m["data"]["topic"] for m in messages]
        assert Topics.SQUARE in topics_received
        assert Topics.TRADES in topics_received
        assert Topics.BANK in topics_received
        assert Topics.WEATHER in topics_received
        assert Topics.NEWS in topics_received

    async def test_multiple_clients_receive_same_message(self):
        bridge = _make_bridge()
        clients = [FakeWS() for _ in range(5)]
        for c in clients:
            bridge._clients.add(c)

        env = _make_envelope(message="Announcement!")
        await bridge._on_nats_message(env)

        for c in clients:
            assert len(c.sent) == 1
            data = json.loads(c.sent[0])
            assert data["data"]["message"] == "Announcement!"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_stop_clears_clients(self):
        bridge = _make_bridge()
        bridge._clients.add(FakeWS())
        bridge._clients.add(FakeWS())
        bridge._nats = AsyncMock()
        bridge._ws_server = MagicMock()
        bridge._ws_server.close = MagicMock()
        bridge._ws_server.wait_closed = AsyncMock()

        await bridge.stop()

        assert bridge.client_count == 0
        assert not bridge._running
        assert bridge._nats is None
