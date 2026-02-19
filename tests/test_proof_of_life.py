"""End-to-end integration test: full message flow. Requires NATS running."""

import asyncio

import pytest

from streetmarket import (
    Accept,
    Bid,
    Envelope,
    MarketBusClient,
    MessageType,
    Offer,
    Topics,
    create_message,
    parse_payload,
    validate_message,
)

pytestmark = pytest.mark.integration


class TestProofOfLife:
    async def test_full_trade_flow(self, bus_client: MarketBusClient):
        """Simulate: farmer offers potatoes → chef bids → farmer accepts."""
        received: list[Envelope] = []
        all_received = asyncio.Event()

        async def handler(env: Envelope) -> None:
            received.append(env)
            if len(received) >= 3:
                all_received.set()

        await bus_client.subscribe(Topics.RAW_GOODS, handler)
        await asyncio.sleep(0.3)

        # 1. Farmer offers potatoes
        offer_env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=Offer(item="potato", quantity=10, price_per_unit=3.0, expires_tick=150),
            tick=42,
        )
        assert validate_message(offer_env) == []
        await bus_client.publish(Topics.RAW_GOODS, offer_env)

        # 2. Chef bids on potatoes
        bid_env = create_message(
            from_agent="chef-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.BID,
            payload=Bid(
                item="potato",
                quantity=5,
                max_price_per_unit=4.0,
                target_agent="farmer-01",
            ),
            tick=42,
        )
        assert validate_message(bid_env) == []
        await bus_client.publish(Topics.RAW_GOODS, bid_env)

        # 3. Farmer accepts the bid
        accept_env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload=Accept(reference_msg_id=bid_env.id, quantity=5),
            tick=43,
        )
        assert validate_message(accept_env) == []
        await bus_client.publish(Topics.RAW_GOODS, accept_env)

        # Wait for all messages
        await asyncio.wait_for(all_received.wait(), timeout=5.0)

        assert len(received) >= 3

        # Verify message types
        types = [env.type for env in received[:3]]
        assert MessageType.OFFER in types
        assert MessageType.BID in types
        assert MessageType.ACCEPT in types

        # Verify payloads are parseable
        for env in received[:3]:
            typed = parse_payload(env)
            assert typed is not None
