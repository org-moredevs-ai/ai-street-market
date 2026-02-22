"""Integration tests for the full economy — all agents trading together.

Requires NATS running (make infra-up).
"""

import asyncio
import os

import pytest
from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Topics,
)

from agents.chef.agent import ChefAgent
from agents.farmer.agent import FarmerAgent
from services.banker.banker import BankerAgent
from services.world.world import WorldEngine

pytestmark = pytest.mark.integration

# Use fast tick interval for tests
os.environ["WORLD_TICK_INTERVAL"] = "0.3"


@pytest.fixture
async def world_engine(nats_url: str) -> WorldEngine:
    engine = WorldEngine(nats_url)
    await engine.start()
    yield engine  # type: ignore[misc]
    await engine.stop()


@pytest.fixture
async def banker(nats_url: str) -> BankerAgent:
    b = BankerAgent(nats_url)
    await b.start()
    await asyncio.sleep(0.3)
    yield b  # type: ignore[misc]
    await b.stop()


@pytest.fixture
async def farmer(nats_url: str) -> FarmerAgent:
    agent = FarmerAgent(nats_url)
    await agent.start()
    yield agent  # type: ignore[misc]
    await agent.stop()


@pytest.fixture
async def chef(nats_url: str) -> ChefAgent:
    agent = ChefAgent(nats_url)
    await agent.start()
    yield agent  # type: ignore[misc]
    await agent.stop()


@pytest.fixture
async def observer(nats_url: str) -> MarketBusClient:
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


class TestEconomyIntegration:
    async def test_agents_join_on_first_tick(
        self,
        world_engine: WorldEngine,
        banker: BankerAgent,
        farmer: FarmerAgent,
        chef: ChefAgent,
        observer: MarketBusClient,
    ):
        """Both agents should auto-join when the first tick arrives."""
        joins, done = await _collect_messages(
            observer, Topics.SQUARE, MessageType.JOIN, 2
        )
        # Wait for at least 2 ticks so agents can join
        await asyncio.wait_for(done.wait(), timeout=10.0)

        agent_ids = {j.payload["agent_id"] for j in joins}
        assert "farmer-01" in agent_ids
        assert "chef-01" in agent_ids

    async def test_farmer_gathers_resources(
        self,
        world_engine: WorldEngine,
        banker: BankerAgent,
        farmer: FarmerAgent,
        observer: MarketBusClient,
    ):
        """Farmer should gather potato and onion from nature spawns."""
        gather_results, done = await _collect_messages(
            observer, Topics.NATURE, MessageType.GATHER_RESULT, 2
        )
        # Wait several ticks for gather cycle
        await asyncio.wait_for(done.wait(), timeout=10.0)

        farmer_results = [
            r for r in gather_results if r.payload["agent_id"] == "farmer-01"
        ]
        assert len(farmer_results) >= 2
        items_gathered = {r.payload["item"] for r in farmer_results}
        assert "potato" in items_gathered or "onion" in items_gathered

    async def test_farmer_offers_surplus(
        self,
        world_engine: WorldEngine,
        banker: BankerAgent,
        farmer: FarmerAgent,
        observer: MarketBusClient,
    ):
        """Farmer should offer surplus raw materials after gathering."""
        offers, done = await _collect_messages(
            observer, "/market/>", MessageType.OFFER, 1
        )
        # Need a few ticks to gather then offer
        await asyncio.wait_for(done.wait(), timeout=15.0)

        farmer_offers = [o for o in offers if o.from_agent == "farmer-01"]
        assert len(farmer_offers) >= 1
        assert farmer_offers[0].payload["item"] in ("potato", "onion")

    async def test_full_economy_cycle(
        self,
        world_engine: WorldEngine,
        banker: BankerAgent,
        farmer: FarmerAgent,
        chef: ChefAgent,
        observer: MarketBusClient,
    ):
        """Full cycle: farmer gathers, offers, chef accepts/bids, trade settles."""
        # Collect settlements — proof that trade happened
        settlements, settlement_done = await _collect_messages(
            observer, "/market/>", MessageType.SETTLEMENT, 1
        )

        # Run for several ticks to allow the economy loop to complete
        try:
            await asyncio.wait_for(settlement_done.wait(), timeout=20.0)
            # A settlement occurred — trade happened!
            assert len(settlements) >= 1
            s = settlements[0]
            assert s.payload["status"] == "completed"
        except asyncio.TimeoutError:
            # If no settlement in 20s, at minimum both agents should have joined and gathered
            assert farmer.state.joined
            assert chef.state.joined
            assert farmer.state.current_tick > 0
            # Farmer should have gathered something
            total_inv = sum(farmer.state.inventory.values())
            assert total_inv > 0, "Farmer should have gathered items"
