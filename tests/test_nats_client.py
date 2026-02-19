"""Integration tests for MarketBusClient. Requires NATS running."""

import asyncio

import pytest

from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Offer,
    Topics,
    create_message,
)

pytestmark = pytest.mark.integration


class TestMarketBusClient:
    async def test_connect_and_disconnect(self, bus_client: MarketBusClient):
        assert bus_client.is_connected
        await bus_client.close()
        assert not bus_client.is_connected

    async def test_publish_and_subscribe(self, bus_client: MarketBusClient):
        received: list[Envelope] = []
        event = asyncio.Event()

        async def handler(env: Envelope) -> None:
            received.append(env)
            event.set()

        await bus_client.subscribe(Topics.RAW_GOODS, handler)
        await asyncio.sleep(0.3)  # Let subscription settle

        offer = Offer(item="potato", quantity=10, price_per_unit=3.0)
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=offer,
            tick=1,
        )
        await bus_client.publish(Topics.RAW_GOODS, env)

        await asyncio.wait_for(event.wait(), timeout=5.0)
        assert len(received) >= 1
        assert received[0].from_agent == "farmer-01"
        assert received[0].payload["item"] == "potato"

    async def test_multiple_messages(self, bus_client: MarketBusClient):
        received: list[Envelope] = []
        done = asyncio.Event()

        async def handler(env: Envelope) -> None:
            received.append(env)
            if len(received) >= 3:
                done.set()

        await bus_client.subscribe(Topics.FOOD, handler)
        await asyncio.sleep(0.3)

        for i in range(3):
            env = create_message(
                from_agent=f"chef-{i:02d}",
                topic=Topics.FOOD,
                msg_type=MessageType.OFFER,
                payload={"item": "soup", "quantity": 1, "price_per_unit": 10.0},
                tick=i + 1,
            )
            await bus_client.publish(Topics.FOOD, env)

        await asyncio.wait_for(done.wait(), timeout=5.0)
        assert len(received) >= 3
