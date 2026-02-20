"""Integration tests for the World Engine. Requires NATS running."""

import asyncio
import os

import pytest
from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Topics,
    create_message,
)

from services.banker.banker import BankerAgent
from services.world.world import WorldEngine

pytestmark = pytest.mark.integration

# Use fast tick interval for tests
os.environ["WORLD_TICK_INTERVAL"] = "0.5"


@pytest.fixture
async def world_engine(nats_url: str) -> WorldEngine:
    """Start a World Engine, tear it down after the test."""
    engine = WorldEngine(nats_url)
    await engine.start()
    yield engine  # type: ignore[misc]
    await engine.stop()


@pytest.fixture
async def banker(nats_url: str) -> BankerAgent:
    """Start a Banker agent, tear it down after the test."""
    b = BankerAgent(nats_url)
    await b.start()
    await asyncio.sleep(0.3)
    yield b  # type: ignore[misc]
    await b.stop()


@pytest.fixture
async def test_client(nats_url: str) -> MarketBusClient:
    """Separate client for sending test messages and receiving results."""
    client = MarketBusClient(nats_url)
    await client.connect()
    yield client  # type: ignore[misc]
    await client.close()


async def _collect_messages(
    client: MarketBusClient,
    topic: str,
    msg_type: MessageType,
    count: int,
) -> tuple[list[Envelope], asyncio.Event]:
    """Subscribe to a topic and collect messages of a specific type."""
    results: list[Envelope] = []
    done = asyncio.Event()

    async def handler(env: Envelope) -> None:
        if env.type == msg_type:
            results.append(env)
            if len(results) >= count:
                done.set()

    await client.subscribe(topic, handler)
    await asyncio.sleep(0.3)
    return results, done


class TestWorldIntegration:
    async def test_tick_publishing(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """World Engine publishes Tick messages to /system/tick."""
        ticks, done = await _collect_messages(
            test_client, Topics.TICK, MessageType.TICK, 2
        )
        await asyncio.wait_for(done.wait(), timeout=5.0)

        assert len(ticks) >= 2
        assert ticks[0].from_agent == "world"
        # Ticks are consecutive (may not start at 1 due to subscription timing)
        first_tick = ticks[0].payload["tick_number"]
        assert ticks[1].payload["tick_number"] == first_tick + 1

    async def test_spawn_publishing(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """World Engine publishes Spawn messages to /world/nature."""
        spawns, done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 1
        )
        await asyncio.wait_for(done.wait(), timeout=5.0)

        assert len(spawns) >= 1
        spawn = spawns[0]
        assert spawn.from_agent == "world"
        assert "spawn_id" in spawn.payload
        assert "items" in spawn.payload
        assert spawn.payload["items"]["potato"] == 20

    async def test_gather_success(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """Agent can successfully gather resources from a spawn."""
        # Collect spawns to get spawn_id
        spawns, spawn_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 1
        )
        # Collect gather results
        results, result_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.GATHER_RESULT, 1
        )

        await asyncio.wait_for(spawn_done.wait(), timeout=5.0)
        spawn_id = spawns[0].payload["spawn_id"]

        # Send a GATHER request
        gather_env = create_message(
            from_agent="farmer-01",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "potato", "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.NATURE, gather_env)

        await asyncio.wait_for(result_done.wait(), timeout=5.0)

        result = results[0]
        assert result.from_agent == "world"
        assert result.type == MessageType.GATHER_RESULT
        assert result.payload["success"] is True
        assert result.payload["quantity"] == 5
        assert result.payload["item"] == "potato"
        assert result.payload["agent_id"] == "farmer-01"

    async def test_gather_fcfs_depletion(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """FCFS: second agent gets partial/no resources after first drains the pool."""
        spawns, spawn_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 1
        )
        results, result_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.GATHER_RESULT, 2
        )

        await asyncio.wait_for(spawn_done.wait(), timeout=5.0)
        spawn_id = spawns[0].payload["spawn_id"]

        # Agent 1 takes all nails (10)
        g1 = create_message(
            from_agent="agent-1",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "nails", "quantity": 10},
            tick=1,
        )
        await test_client.publish(Topics.NATURE, g1)
        await asyncio.sleep(0.3)

        # Agent 2 tries to get nails — should fail
        g2 = create_message(
            from_agent="agent-2",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "nails", "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.NATURE, g2)

        await asyncio.wait_for(result_done.wait(), timeout=5.0)

        # Find results by agent
        r1 = next(r for r in results if r.payload["agent_id"] == "agent-1")
        r2 = next(r for r in results if r.payload["agent_id"] == "agent-2")

        assert r1.payload["success"] is True
        assert r1.payload["quantity"] == 10
        assert r2.payload["success"] is False
        assert r2.payload["quantity"] == 0

    async def test_expired_spawn_rejected(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """Gather with an expired spawn_id is rejected."""
        spawns, spawn_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 2
        )
        results, result_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.GATHER_RESULT, 1
        )

        # Wait for at least 2 spawns (tick 1 and tick 2)
        await asyncio.wait_for(spawn_done.wait(), timeout=5.0)

        # Use the OLD spawn_id (tick 1) — should be expired now
        old_spawn_id = spawns[0].payload["spawn_id"]

        gather_env = create_message(
            from_agent="farmer-01",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": old_spawn_id, "item": "potato", "quantity": 5},
            tick=2,
        )
        await test_client.publish(Topics.NATURE, gather_env)

        await asyncio.wait_for(result_done.wait(), timeout=5.0)

        result = results[0]
        assert result.payload["success"] is False
        assert result.payload["quantity"] == 0

    async def test_banker_credits_on_gather(
        self,
        world_engine: WorldEngine,
        banker: BankerAgent,
        test_client: MarketBusClient,
    ):
        """Banker credits agent inventory when it receives a successful GATHER_RESULT."""
        spawns, spawn_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 1
        )
        results, result_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.GATHER_RESULT, 1
        )

        await asyncio.wait_for(spawn_done.wait(), timeout=5.0)
        spawn_id = spawns[0].payload["spawn_id"]

        # Gather
        gather_env = create_message(
            from_agent="farmer-01",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "potato", "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.NATURE, gather_env)

        await asyncio.wait_for(result_done.wait(), timeout=5.0)
        # Give banker time to process the GATHER_RESULT
        await asyncio.sleep(0.5)

        # Check banker state — farmer-01 should have been auto-created + credited
        account = banker.state.get_account("farmer-01")
        assert account is not None
        assert account.inventory.get("potato") == 5

    async def test_self_loop_prevention(
        self, world_engine: WorldEngine, test_client: MarketBusClient
    ):
        """World Engine should not process its own SPAWN or GATHER_RESULT messages."""
        spawns, spawn_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.SPAWN, 1
        )
        results, result_done = await _collect_messages(
            test_client, Topics.NATURE, MessageType.GATHER_RESULT, 1
        )

        await asyncio.wait_for(spawn_done.wait(), timeout=5.0)
        spawn_id = spawns[0].payload["spawn_id"]

        # Send a valid gather
        gather_env = create_message(
            from_agent="farmer-01",
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER,
            payload={"spawn_id": spawn_id, "item": "potato", "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.NATURE, gather_env)

        await asyncio.wait_for(result_done.wait(), timeout=5.0)
        # Wait to see if any extra results appear from self-loop
        await asyncio.sleep(1.0)

        # Should be exactly 1 gather result
        our_results = [
            r for r in results
            if r.payload.get("reference_msg_id") == gather_env.id
        ]
        assert len(our_results) == 1
